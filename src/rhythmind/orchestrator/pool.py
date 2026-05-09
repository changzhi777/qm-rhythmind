# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
orchestrator/pool.py — Agent 单例池

问题背景：
  每次 HTTP 请求都 new MetricsAgent / DataAgent / CoachAgent，
  导致 MemoryManager / SkillEngine / QMDClient 重复初始化，
  在高并发下产生不必要的连接开销。

解决方案：
  AgentPool 按 user_id 缓存三个 Agent 实例，
  采用 LRU 策略（TTL=30min），asyncio.Lock 保证线程安全。

使用方式：
  # 在 FastAPI lifespan 中初始化
  agent_pool = AgentPool(max_users=1000, ttl_seconds=1800)

  # 在路由中获取
  async with agent_pool.acquire(user_id) as agents:
      result = await agents.metrics.run(ctx)

设计约束：
  - Agent 实例不共享状态（user_id 完全隔离）
  - InfluxClient 单例（全局共享，连接池已内置）
  - MLX 模型通过 _MODEL_CACHE 热缓存（MLXAdapter 内部）
  - 池满时 LRU 淘汰最久未使用条目
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator

from rhythmind.adapters.influx_client import InfluxClient
from rhythmind.agents.coach_agent import CoachAgent
from rhythmind.agents.data_agent import DataAgent
from rhythmind.agents.metrics_agent import MetricsAgent

logger = logging.getLogger(__name__)


# ── 共享资源单例 ──────────────────────────────────────────────────────────────

# InfluxDB 客户端全局单例（内部有 aiohttp.ClientSession 连接池）
_influx_singleton: InfluxClient | None = None
_influx_lock = asyncio.Lock()


async def get_shared_influx() -> InfluxClient:
    """获取全局共享的 InfluxClient（懒初始化）。"""
    global _influx_singleton
    if _influx_singleton is None:
        async with _influx_lock:
            if _influx_singleton is None:
                _influx_singleton = InfluxClient()
                logger.info("pool.influx_singleton created")
    return _influx_singleton


# ── Agent 组合体 ──────────────────────────────────────────────────────────────

@dataclass
class AgentBundle:
    """
    某个 user_id 对应的 Agent 实例组合。

    三个 Agent 共享同一个 InfluxClient（节省连接）。
    """
    user_id: str
    metrics: MetricsAgent
    data: DataAgent
    coach: CoachAgent
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        """更新最近使用时间戳（LRU 支持）。"""
        self.last_used = time.monotonic()

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_used


# ── AgentPool ─────────────────────────────────────────────────────────────────

class AgentPool:
    """
    LRU Agent 实例池。

    参数：
        max_users:   最多缓存多少个 user 的 Agent 组（默认 500）
        ttl_seconds: Agent 组最大闲置时间（秒），超过则淘汰（默认 30min）

    线程安全：
        _lock 保护 _pool，所有读写均在锁内完成。

    MLX 热缓存说明：
        MLXAdapter._MODEL_CACHE 是模块级字典，模型一旦加载便常驻内存，
        AgentPool 无需额外处理——获取 AgentBundle 时模型已热。
    """

    def __init__(self, max_users: int = 500, ttl_seconds: float = 1800) -> None:
        self.max_users = max_users
        self.ttl_seconds = ttl_seconds
        # OrderedDict 维护 LRU 顺序（最近使用的在末尾）
        self._pool: OrderedDict[str, AgentBundle] = OrderedDict()
        self._lock = asyncio.Lock()
        logger.info("AgentPool init max_users=%d ttl=%ds", max_users, ttl_seconds)

    # ── 公开接口 ──────────────────────────────────────────────────────────

    @asynccontextmanager
    async def acquire(self, user_id: str) -> AsyncGenerator[AgentBundle, None]:
        """
        上下文管理器：获取（或创建）user_id 对应的 AgentBundle。

        用法::

            async with pool.acquire(user_id) as agents:
                result = await agents.metrics.run(ctx)
        """
        bundle = await self._get_or_create(user_id)
        try:
            yield bundle
        finally:
            bundle.touch()  # 归还时更新时间戳

    async def invalidate(self, user_id: str) -> None:
        """强制淘汰某个 user 的 Agent 组（如账号退出）。"""
        async with self._lock:
            self._pool.pop(user_id, None)
            logger.debug("pool.invalidate user=%s", user_id)

    async def purge_expired(self) -> int:
        """
        清理所有超过 TTL 的条目，返回清理数量。

        建议在 FastAPI lifespan 的后台任务中定期调用（每 5 分钟一次）。
        """
        now = time.monotonic()
        expired = [
            uid for uid, bundle in self._pool.items()
            if (now - bundle.last_used) > self.ttl_seconds
        ]
        async with self._lock:
            for uid in expired:
                self._pool.pop(uid, None)
        if expired:
            logger.info("pool.purge expired=%d", len(expired))
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._pool)

    def stats(self) -> dict:
        """诊断用：返回当前池状态摘要。"""
        now = time.monotonic()
        return {
            "pool_size": len(self._pool),
            "max_users": self.max_users,
            "ttl_seconds": self.ttl_seconds,
            "entries": [
                {
                    "user_id": uid,
                    "age_s": round(now - b.created_at, 1),
                    "idle_s": round(now - b.last_used, 1),
                }
                for uid, b in self._pool.items()
            ],
        }

    # ── 内部实现 ──────────────────────────────────────────────────────────

    async def _get_or_create(self, user_id: str) -> AgentBundle:
        async with self._lock:
            # 命中缓存
            if user_id in self._pool:
                bundle = self._pool[user_id]
                # TTL 检查
                if bundle.idle_seconds <= self.ttl_seconds:
                    # 移到末尾（LRU 更新）
                    self._pool.move_to_end(user_id)
                    logger.debug("pool.hit user=%s idle=%.1fs", user_id, bundle.idle_seconds)
                    return bundle
                else:
                    # TTL 到期，删除后重建
                    del self._pool[user_id]
                    logger.debug("pool.ttl_expired user=%s", user_id)

            # 容量满 → 淘汰最久未使用（LRU 头部）
            if len(self._pool) >= self.max_users:
                evicted_uid, _ = self._pool.popitem(last=False)
                logger.info("pool.evict user=%s (LRU)", evicted_uid)

            # 创建新 AgentBundle
            bundle = await self._create_bundle(user_id)
            self._pool[user_id] = bundle
            logger.debug("pool.miss created user=%s pool_size=%d", user_id, len(self._pool))
            return bundle

    @staticmethod
    async def _create_bundle(user_id: str) -> AgentBundle:
        """实例化三个 Agent，共享 InfluxClient。"""
        influx = await get_shared_influx()
        return AgentBundle(
            user_id=user_id,
            metrics=MetricsAgent(user_id=user_id, influx=influx),
            data=DataAgent(user_id=user_id),
            coach=CoachAgent(user_id=user_id),
        )


# ── 全局单例（供 FastAPI deps 使用）─────────────────────────────────────────

_pool_instance: AgentPool | None = None


def get_agent_pool(max_users: int = 500, ttl_seconds: float = 1800) -> AgentPool:
    """获取全局 AgentPool 单例（首次调用时创建）。"""
    global _pool_instance
    if _pool_instance is None:
        _pool_instance = AgentPool(max_users=max_users, ttl_seconds=ttl_seconds)
    return _pool_instance
