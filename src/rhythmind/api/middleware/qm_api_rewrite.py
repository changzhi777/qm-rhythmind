# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
api/middleware/qm_api_rewrite.py — /qm/api/v1/* 路径重写

背景:
  前端 Next.js basePath=/qm,统一从 API_BASE('/qm/api') 拼接。
  后端路由分两套:
    - dashboard.py 显式 prefix='/qm/api'
    - 其他 (health/medical/llm-observe/feishu/privacy/admin/auth) 在 main.py 挂 prefix='/api/v1'
  旧版前端 (2026-06-24 之前) 调用 fetchWithAuth('/v1/llm-observe/...') 会被拼成
  '/qm/api/v1/llm-observe/...' → uvicorn 无此路由 → 404。

修复:
  ASGI 中间件在路由匹配前把 /qm/api/v1/* 重写为 /api/v1/*,
  让 /qm/api/v1/llm-observe/... 落到正确的 v1 路由上。
  对 /qm/api/* (dashboard 自身) 不动,保留 dashboard.py 显式 prefix 的语义。

兼容:
  旧前端 (V1_BASE 写法 / 直接走 /qm/api/v1) 自动修复;
  新前端 (2026-06-25 commit ead9ac6,改用 V1_BASE='/api' 走 /api/v1) 不受影响;
  完全不影响 /qm/api/dashboard、/api/v1/* 原始路径。
"""
from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# 触发重写的前缀(只针对 v1 API;dashboard.py 的 /qm/api/* 不动)
_REWRITE_PREFIX = "/qm/api/v1/"


class QmApiV1RewriteMiddleware(BaseHTTPMiddleware):
    """
    将 /qm/api/v1/* 重写为 /api/v1/*,仅在请求路径命中 _REWRITE_PREFIX 时触发。

    实现细节:
      - 修改 request.scope['path'] 和 request.scope['raw_path']
      - uvicorn 在收到请求后会把 path 传给 ASGI app 的 receive/scope,
        改 scope['path'] 就够;raw_path 同步改以保一致
      - 不修改 query string / headers / body
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        original_path = request.scope.get("path", "")
        if original_path.startswith(_REWRITE_PREFIX):
            # /qm/api/v1/llm-observe/... → /api/v1/llm-observe/...
            new_path = "/api/v1/" + original_path[len(_REWRITE_PREFIX):]
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("latin-1")
            logger.debug(
                "qm_api_v1_rewrite.rewrote %s -> %s", original_path, new_path,
            )
        return await call_next(request)
