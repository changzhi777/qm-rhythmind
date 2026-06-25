"""
api/routers/auth.py — 认证端点(2026-06-25)

新增端点:
  POST /api/v1/auth/login — 接受 user_id,返回 JWT
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel

from rhythmind.config import settings

logger = __import__("logging").getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── 测试账户白名单(生产模式仅允许这些用户) ─────────────────────
_ALLOWED_USERS: set[str] = {
    "garmin_user_001",
    "athlete_demo_001",
    "athlete_zhang",
}


class LoginRequest(BaseModel):
    user_id: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int  # 秒
    user_id: str


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    """登录:接受 user_id,签发 30 天有效 JWT。

    生产模式安全检查:
    - 必须是白名单内的测试账户
    - JWT_SECRET 必须非默认

    开发模式:任何 user_id 都接受
    """
    user_id = (payload.user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    # 生产模式:白名单检查
    if settings.env == "prod" and user_id not in _ALLOWED_USERS:
        logger.warning("auth.login rejected user_id=%s (not in allowlist)", user_id)
        raise HTTPException(status_code=403, detail="User not in allowlist")

    secret = settings.jwt_secret
    if not secret or secret == "change-me-in-prod":
        raise HTTPException(
            status_code=500, detail="JWT_SECRET not configured (check /data/.env)"
        )

    # 签发 30 天 JWT
    now = datetime.now(UTC)
    expires = now + timedelta(days=30)
    token: str = jwt.encode(
        {
            "sub": user_id,
            "user_id": user_id,
            "iat": now,
            "exp": expires,
        },
        secret,
        algorithm="HS256",
    )
    return LoginResponse(
        access_token=token,
        expires_in=30 * 86400,
        user_id=user_id,
    )


@router.get("/whoami")
async def whoami() -> dict[str, Any]:
    """健康检查端点(返回当前配置摘要)"""
    return {
        "env": settings.env,
        "allowlist_size": len(_ALLOWED_USERS),
        "jwt_secret_configured": settings.jwt_secret not in ("", "change-me-in-prod"),
    }