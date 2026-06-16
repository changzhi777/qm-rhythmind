# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/rate_limit.py — Redis 固定窗口限流器（per-user / per-IP / per-route）

为什么不用 slowapi:
  - slowapi 接口上是同步装饰器，配合 async FastAPI 与 dependency 体系不顺
  - 我们已经依赖 redis.asyncio，复用即可，不引入新组件
  - 固定窗口 + INCR + EXPIRE 是原子操作，对生产 QPS 足够

降级策略:
  - Redis 不可达时：放行 + 打 WARN 日志（与 LoopGuard 一致，避免单点故障让业务停摆）
  - 不应作为唯一防线 —— 真正抗 DDoS 应在 Ingress/WAF 层做

使用:
    from rhythmind.api.rate_limit import rate_limit_user

    @router.post("/upload", dependencies=[Depends(rate_limit_user("upload", 30, 60))])
    async def upload(...): ...

  上面表示同一 user_id 在 60 秒窗口内最多请求 30 次 /upload。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from rhythmind.api.deps import CurrentUserId
from rhythmind.config import settings

logger = logging.getLogger(__name__)


# ── 单例 Redis 连接 ───────────────────────────────────────────────────────────

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _redis_client


async def _check_and_incr(key: str, limit: int, window_sec: int) -> tuple[bool, int, int]:  # noqa: E501
    """
    INCR + EXPIRE 原子计数。

    返回 (allowed, current_count, retry_after_sec)。
    Redis 故障时 (True, 0, 0) —— 降级放行。
    """
    try:
        r = _get_redis()
        # 使用 pipeline 减少 round-trip
        async with r.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_sec, nx=True)  # 仅在不存在时设 TTL（首次窗口）
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()

        if count > limit:
            retry_after = max(int(ttl), 1)
            return False, count, retry_after
        return True, count, 0
    except Exception as exc:
        logger.warning("rate_limit.redis_unavailable key=%s error=%s", key, exc)
        return True, 0, 0  # fail-open


# ── 工厂：per-user-per-route 限流依赖 ────────────────────────────────────────

def rate_limit_user(
    route_key: str,
    limit: int,
    window_sec: int,
) -> Callable:
    """
    返回一个 FastAPI 依赖：限制同一 user_id 在 window_sec 内对 route_key 的请求数。

    例：rate_limit_user("upload", 30, 60) — 每用户每分钟最多 30 次 /upload。
    """
    async def _dep(user_id: CurrentUserId) -> None:
        key = f"rl:user:{route_key}:{user_id}"
        allowed, count, retry_after = await _check_and_incr(key, limit, window_sec)
        if not allowed:
            logger.info(
                "rate_limit.blocked user_id=%s route=%s count=%d retry_after=%ds",
                user_id, route_key, count, retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，请 {retry_after} 秒后重试",
                headers={"Retry-After": str(retry_after)},
            )
    return _dep


# ── 工厂：per-IP-per-route 限流依赖（防匿名/扫描）────────────────────────────

def rate_limit_ip(
    route_key: str,
    limit: int,
    window_sec: int,
) -> Callable:
    async def _dep(request: Request) -> None:
        # X-Forwarded-For 优先（反向代理后），否则用直连 client.host
        xff = request.headers.get("x-forwarded-for", "")
        ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")  # noqa: E501
        key = f"rl:ip:{route_key}:{ip}"
        allowed, count, retry_after = await _check_and_incr(key, limit, window_sec)
        if not allowed:
            logger.info(
                "rate_limit.blocked ip=%s route=%s count=%d retry_after=%ds",
                ip, route_key, count, retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"来源 IP 请求过于频繁，请 {retry_after} 秒后重试",
                headers={"Retry-After": str(retry_after)},
            )
    return _dep


# ── 默认配额（可通过 settings 覆盖）─────────────────────────────────────────

# 健康数据上传：昂贵的 LLM 调用，严格限
LIMIT_UPLOAD_PER_USER  = (30, 60)    # 每用户每分钟 30 次
LIMIT_UPLOAD_PER_IP    = (60, 60)    # 每 IP 每分钟 60 次

# 文本对话：稍宽松
LIMIT_CHAT_PER_USER    = (60, 60)
LIMIT_CHAT_PER_IP      = (120, 60)
