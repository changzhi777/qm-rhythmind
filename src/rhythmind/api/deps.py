# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/deps.py — FastAPI 依赖注入

提供：
  - get_current_user_id : JWT 解析 → user_id
  - get_router          : HealthRouter 单例
  - get_pool            : AgentPool 单例（LRU Agent 实例缓存）
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jose import JWTError, jwt

from rhythmind.config import settings
from rhythmind.orchestrator import HealthRouter
from rhythmind.orchestrator.pool import AgentPool, get_agent_pool

logger = logging.getLogger(__name__)

# ── JWT ───────────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=True)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """
    解析 Bearer JWT → user_id。

    开发环境（env=dev）允许直接传 user_id 作为 token（便于 curl 测试）::

        curl -H "Authorization: Bearer user_abc" http://localhost:8000/api/v1/health/upload
    """
    token = credentials.credentials

    if settings.env == "dev" and not token.startswith("eyJ"):
        logger.debug("deps.dev_mode user_id=%s", token)
        return token

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing sub",
            )
        return user_id
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {e}",
        )


# ── HealthRouter 单例 ─────────────────────────────────────────────────────────

_router_instance: HealthRouter | None = None


def get_router() -> HealthRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = HealthRouter()
    return _router_instance


# ── AgentPool 单例 ────────────────────────────────────────────────────────────

def get_pool() -> AgentPool:
    """
    返回全局 AgentPool 单例。

    池参数从 settings 读取（可通过 .env 调整）：
      AGENT_POOL_MAX_USERS  = 500   （默认）
      AGENT_POOL_TTL        = 1800  （默认，秒）
    """
    max_users = getattr(settings, "agent_pool_max_users", 500)
    ttl = getattr(settings, "agent_pool_ttl", 1800)
    return get_agent_pool(max_users=max_users, ttl_seconds=ttl)


# ── 类型别名（简化路由函数签名）────────────────────────────────────────────────

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
RouterDep     = Annotated[HealthRouter, Depends(get_router)]
PoolDep       = Annotated[AgentPool, Depends(get_pool)]
