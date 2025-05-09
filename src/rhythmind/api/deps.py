# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/deps.py — FastAPI 依赖注入

提供：
  - get_current_user_id: JWT 解析 → user_id
  - get_router: HealthRouter 单例
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jose import JWTError, jwt

from rhythmind.config import settings
from rhythmind.orchestrator import HealthRouter

logger = logging.getLogger(__name__)

# ── JWT ───────────────────────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=True)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """
    解析 Bearer JWT → user_id。

    开发环境（env=dev）允许直接传 user_id 作为 token（便于 curl 测试）。
    """
    token = credentials.credentials

    if settings.env == "dev" and not token.startswith("eyJ"):
        # Dev 快捷：直接把 token 当 user_id 使用
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


# ── HealthRouter 单例 ─────────────────────────────────────────────────────

_router_instance: HealthRouter | None = None


def get_router() -> HealthRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = HealthRouter()
    return _router_instance


# 类型别名（简化路由函数签名）
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
RouterDep = Annotated[HealthRouter, Depends(get_router)]
