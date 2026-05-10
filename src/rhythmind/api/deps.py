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

    开发便利模式（仅本地）：仅当所有以下条件全部满足时，
    才接受非 JWT 的明文 user_id 作为 Bearer token：

      1) settings.env == "dev"
      2) settings.dev_auth_bypass is True   （需显式开启）
      3) settings.env != "prod"             （额外冗余守卫）

    生产部署中 dev_auth_bypass 强制为 False，且 config.py 的 validator
    会在 ENV=prod 且 dev_auth_bypass=True 时直接拒绝启动。
    任何环境变量误配置都不会再造成"传 alice 即登录 alice"的越权。
    """
    token = credentials.credentials

    # ── 严格的开发便利通道（非生产 + 显式开关）─────────────────────────
    # dev_auth_bypass 的语义是"非生产 + 显式开启"，因此 dev 与 test 都允许。
    # ENV=prod 时 config.assert_production_safe() 会直接拒绝 dev_auth_bypass=True
    # 启动，所以这里的 settings.env != "prod" 是冗余防御（深度防御）。
    if (
        settings.env != "prod"
        and getattr(settings, "dev_auth_bypass", False) is True
        and not token.startswith("eyJ")
    ):
        logger.warning(
            "deps.dev_auth_bypass ENABLED env=%s user_id=%s — never enable in prod",
            settings.env, token,
        )
        try:
            from rhythmind.audit import AuditEvent, audit_log
            audit_log(AuditEvent.AUTH_BYPASS_USED, user_id=token, env=settings.env)
        except Exception:
            pass
        return token

    # ── 标准 JWT 解析 ────────────────────────────────────────────────────
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
