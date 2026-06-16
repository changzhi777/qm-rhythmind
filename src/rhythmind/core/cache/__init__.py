# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/cache/ — Redis 缓存层

三层缓存策略：
  1. 装饰器缓存   — 任意 async 函数结果缓存（TTL 可调）
  2. Session 缓存 — 用户会话级数据（user_id + session_id）
  3. Fact 缓存     — FactManager 查询结果（短 TTL，热数据）

TTL 设计原则：
  - Session 数据：30 分钟（与 JWT 过期时间对齐）
  - Fact 缓存：5 分钟（可穿戴数据更新频率）
  - LLM 响应缓存：10 分钟（相同 prompt 返回相同结果）

Redis 故障策略：所有 get 返回 None（不抛异常），set 直接穿透。
"""
from __future__ import annotations

import json as _json
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar, cast

import redis.asyncio as aioredis

from rhythmind.config import settings

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# ── 单例 Redis 连接 ───────────────────────────────────────────────────────────

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ── 工具函数 ────────────────────────────────────────────────────────────────

async def _get(key: str) -> Any | None:
    try:
        r = _get_redis()
        val = await r.get(key)
        if val is None:
            return None
        return _json.loads(val)
    except Exception as exc:
        logger.warning("cache.redis_get_error key=%s %s", key, exc)
        return None


async def _set(key: str, value: Any, ttl_sec: int) -> bool:
    try:
        r = _get_redis()
        await r.set(key, _json.dumps(value), ex=ttl_sec)
        return True
    except Exception as exc:
        logger.warning("cache.redis_set_error key=%s %s", key, exc)
        return False


async def _delete(key: str) -> None:
    try:
        r = _get_redis()
        await r.delete(key)
    except Exception as exc:
        logger.warning("cache.redis_delete_error key=%s %s", key, exc)


# ── 装饰器缓存 ────────────────────────────────────────────────────────────────

def cache_async[**P](
    prefix: str,
    ttl_seconds: int = 600,
    *,
    key_func: Callable[P, str] | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T | None]]]:
    """
    异步函数结果 Redis 缓存装饰器。

    用途：缓存 LLM 调用结果、QMD 查询结果等耗时操作。
    Redis 故障时：get 返回 None（不抛异常），set 直接穿透。

    Args:
        prefix:     key 前缀，完整 key = f"{prefix}:{identifiers}"
        ttl_seconds: TTL，默认 10 分钟
        key_func:   生成 key 标识的函数，默认所有位置参数下划线连接

    用法::

        @cache_async("llm_response", ttl_seconds=600)
        async def call_llm(prompt: str, model: str) -> str:
            ...

        result = await call_llm("hello", "gpt-4")
        # 首次调用执行 LLM，后续调用命中缓存

    注意：被装饰函数的所有参数必须可 JSON 序列化。
    """
    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T | None]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T | None:
            # 构建 key
            if key_func is not None:
                ident = key_func(*args, **kwargs)
            else:
                ident = "_".join(str(a) for a in args)
            key = f"{prefix}:{ident}"

            # 尝试从缓存读取
            cached = await _get(key)
            if cached is not None:
                logger.debug("cache.hit key=%s", key)
                return cast(T | None, cached)

            # 执行原函数
            logger.debug("cache.miss key=%s", key)
            result = await fn(*args, **kwargs)

            # 缓存结果
            await _set(key, result, ttl_seconds)
            return result

        return wrapper
    return decorator


# ── Session 缓存 ───────────────────────────────────────────────────────────

class SessionCache:
    """
    用户会话级数据缓存。

    用途：缓存用户上传数据后的中间结果（避免重复 LLM 调用）、
    意图分类结果等。

    key = f"session:{user_id}:{session_id}"
    TTL = 30 分钟（与 JWT 过期时间对齐）
    """

    SESSION_TTL = 30 * 60  # 30 分钟

    @staticmethod
    async def get(user_id: str, session_id: str) -> dict[str, Any] | None:
        key = f"session:{user_id}:{session_id}"
        return cast(dict[str, Any] | None, await _get(key))

    @staticmethod
    async def set(user_id: str, session_id: str, data: dict[str, Any]) -> None:
        key = f"session:{user_id}:{session_id}"
        await _set(key, data, SessionCache.SESSION_TTL)

    @staticmethod
    async def delete(user_id: str, session_id: str) -> None:
        key = f"session:{user_id}:{session_id}"
        await _delete(key)

    @staticmethod
    async def clear_user(user_id: str) -> None:
        """清除用户所有 session 缓存（登出时调用）。"""
        try:
            r = _get_redis()
            cursor = 0
            pattern = f"session:{user_id}:*"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("cache.clear_user_error user_id=%s %s", user_id, exc)


# ── Fact 缓存 ───────────────────────────────────────────────────────────────

class FactCache:
    """
    FactManager 查询结果缓存。

    用途：热点用户数据的短期缓存（如当前心率、步数等可穿戴指标），
    降低 InfluxDB / PostgreSQL 查询压力。

    key = f"fact:{user_id}:{subject}:{predicate}"
    TTL = 5 分钟（高频更新数据）
    """

    FACT_TTL = 5 * 60  # 5 分钟

    @staticmethod
    async def get(user_id: str, subject: str, predicate: str) -> dict[str, Any] | None:
        key = f"fact:{user_id}:{subject}:{predicate}"
        return cast(dict[str, Any] | None, await _get(key))

    @staticmethod
    async def set(
        user_id: str, subject: str, predicate: str, data: dict[str, Any]
    ) -> None:
        key = f"fact:{user_id}:{subject}:{predicate}"
        await _set(key, data, FactCache.FACT_TTL)

    @staticmethod
    async def invalidate(user_id: str, subject: str, predicate: str) -> None:
        key = f"fact:{user_id}:{subject}:{predicate}"
        await _delete(key)

    @staticmethod
    async def invalidate_user(user_id: str) -> None:
        """用户数据更新时清除所有 fact 缓存。"""
        try:
            r = _get_redis()
            cursor = 0
            pattern = f"fact:{user_id}:*"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning("cache.fact_invalidate_user_error user_id=%s %s", user_id, exc)  # noqa: E501


# ── 意图分类结果缓存 ─────────────────────────────────────────────────────────

class IntentCache:
    """
    用户意图分类结果缓存。

    用途：同一用户短时间内的重复问题无需重新分类，
    直接返回上一次的路由结果。

    key = f"intent:{user_id}:{text_hash}"
    TTL = 10 分钟
    """

    INTENT_TTL = 10 * 60  # 10 分钟

    @staticmethod
    async def get(user_id: str, text_hash: str) -> str | None:
        key = f"intent:{user_id}:{text_hash}"
        return cast(str | None, await _get(key))

    @staticmethod
    async def set(user_id: str, text_hash: str, intent: str) -> None:
        key = f"intent:{user_id}:{text_hash}"
        await _set(key, intent, IntentCache.INTENT_TTL)