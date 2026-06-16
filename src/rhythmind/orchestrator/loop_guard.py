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

分级限流（v0.2.1+）：
  loop_guard_tiered_limits 配置按 intent 设置不同上限。
  例：greeting 10次/24h, query 30次/24h, __default__ 5次/24h

可观测性：
  每次 is_cooling_down() 调用均记录指标：
    loop_guard_calls_total{user_id, intent, result}
    result = "allowed" | "throttled" | "error"
"""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from rhythmind.config import settings

logger = logging.getLogger(__name__)

# ── Prometheus 指标（可选导入）──────────────────────────────────────────────

try:
    from prometheus_client import Counter  # type: ignore[import-not-found]
    _LOOP_GUARD_CALLS = Counter(
        "rhythmind_loop_guard_calls_total",
        "LoopGuard 调用计数",
        ["intent", "result"],  # result=allowed|throttled|error
    )
except ImportError:
    _LOOP_GUARD_CALLS = None


def _record_call(intent: str, result: str) -> None:
    if _LOOP_GUARD_CALLS is not None:
        _LOOP_GUARD_CALLS.labels(intent=intent, result=result).inc()


def _parse_tiered_limits() -> dict[str, int]:
    """解析 loop_guard_tiered_limits JSON 为 dict[int]。"""
    raw = settings.loop_guard_tiered_limits
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("loop_guard.tiered_limits.parse_error raw=%s", raw[:100])
        return {}


class LoopGuard:
    """Redis TTL 防环（单例使用，在 HealthRouter 中持有）。"""

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or settings.redis_url
        self._redis: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            url, encoding="utf-8", decode_responses=True
        )
        self._ttl_sec = settings.loop_guard_ttl_hours * 3600
        self._max_calls = settings.loop_guard_max_calls
        self._tiered_limits = _parse_tiered_limits()

    def _get_limit(self, intent: str) -> int:
        if intent in self._tiered_limits:
            return self._tiered_limits[intent]
        return self._tiered_limits.get("__default__", self._max_calls)

    async def is_cooling_down(self, user_id: str, intent: str) -> bool:
        """
        检查是否处于冷却期。

        同时递增调用计数（原子操作）。
        Returns:
            True  — 已达上限，应拒绝本次调用
            False — 正常放行
        """
        limit = self._get_limit(intent)
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

            if count > limit:
                logger.warning(
                    "loop_guard.cooling user=%s intent=%s count=%d limit=%d ttl=%d",
                    user_id, intent, count, limit, ttl,
                )
                _record_call(intent, "throttled")
                return True
            _record_call(intent, "allowed")
            return False
        except Exception as e:
            logger.error("loop_guard.redis_error=%s fallback=allow", e)
            _record_call(intent, "error")
            return False  # Redis 故障时放行，不阻断主流程

    async def reset(self, user_id: str, intent: str) -> None:
        """手动重置（测试或管理员干预用）。"""
        key = f"loop:{user_id}:{intent}"
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()
