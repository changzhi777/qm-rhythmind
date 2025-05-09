# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
orchestrator/loop_guard.py — Redis TTL 防环卫兵

防止 RehabAgent 等在自我调整循环中被反复触发。

策略：
  key = f"loop:{user_id}:{intent}"
  TTL = settings.loop_guard_ttl_hours * 3600
  24h 内同 user+intent 超过 max_calls 次 → is_cooling_down() = True
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from rhythmind.config import settings

logger = logging.getLogger(__name__)


class LoopGuard:
    """Redis TTL 防环（单例使用，在 HealthRouter 中持有）。"""

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or settings.redis_url
        self._redis: aioredis.Redis = aioredis.from_url(
            url, encoding="utf-8", decode_responses=True
        )
        self._ttl_sec = settings.loop_guard_ttl_hours * 3600
        self._max_calls = settings.loop_guard_max_calls

    async def is_cooling_down(self, user_id: str, intent: str) -> bool:
        """
        检查是否处于冷却期。

        同时递增调用计数（原子操作）。
        Returns:
            True  — 已达上限，应拒绝本次调用
            False — 正常放行
        """
        key = f"loop:{user_id}:{intent}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count_str, ttl = await pipe.execute()
            count = int(count_str)

            # 首次写入时设置 TTL
            if ttl < 0:
                await self._redis.expire(key, self._ttl_sec)

            if count > self._max_calls:
                logger.warning(
                    "loop_guard.cooling user=%s intent=%s count=%d ttl=%d",
                    user_id, intent, count, ttl,
                )
                return True
            return False
        except Exception as e:
            logger.error("loop_guard.redis_error=%s fallback=allow", e)
            return False  # Redis 故障时放行，不阻断主流程

    async def reset(self, user_id: str, intent: str) -> None:
        """手动重置（测试或管理员干预用）。"""
        key = f"loop:{user_id}:{intent}"
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
