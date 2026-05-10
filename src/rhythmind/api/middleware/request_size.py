# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
api/middleware/request_size.py — 请求体大小硬上限

设计:
  - 在读取 body 之前用 Content-Length 头快速拒绝（413 Payload Too Large）
  - 对于 chunked / 无 Content-Length 的请求：用流式读取并累计；超限即中断
  - SSE / 长连接请求（GET / WebSocket）跳过

为什么需要:
  - 防内存耗尽（恶意构造超大 JSON 触发 pydantic 解析爆栈）
  - 防 LLM token 预算被滥用（超大 prompt 即便通过 pydantic 仍然贵）
  - 与 Ingress 层（nginx `client_max_body_size`）形成纵深防御

阈值:
  settings.max_request_body_bytes (默认 1 MiB)
  设为 0 则禁用（不推荐）。
"""
from __future__ import annotations

import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from rhythmind.config import settings

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    限制单个请求 body 大小。
    超限返回 413（RFC 7231）+ structlog 记录。
    """

    def __init__(self, app, max_bytes: int | None = None) -> None:
        super().__init__(app)
        # 允许构造时覆盖，便于单测
        self._max_bytes = max_bytes if max_bytes is not None else settings.max_request_body_bytes

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._max_bytes <= 0:
            return await call_next(request)

        # 1) 优先看 Content-Length（绝大多数客户端会带）
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                length = int(cl)
            except ValueError:
                length = 0
            if length > self._max_bytes:
                logger.warning(
                    "request_size.rejected path=%s declared=%d limit=%d",
                    request.url.path, length, self._max_bytes,
                )
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (>{self._max_bytes} bytes)"},
                )

        # 2) 没带 Content-Length 的（chunked / streaming）—— 流式累计
        # 注意：starlette 的 BaseHTTPMiddleware 会缓存 receive callable，
        # 直接通过 await request.body() 触发完整读取并量度。
        # 对 chunked 请求做这一步会损失一点流式优势，但对我们这种纯 JSON API 业务可以接受。
        if cl is None and request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > self._max_bytes:
                logger.warning(
                    "request_size.rejected_chunked path=%s actual=%d limit=%d",
                    request.url.path, len(body), self._max_bytes,
                )
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (>{self._max_bytes} bytes)"},
                )
            # 重要：缓存 body 让后续 handler 仍能读到
            # starlette 的 Request 会自动 cache body 在 request._body，
            # 所以 await request.body() 第二次会直接返回缓存值。

        return await call_next(request)
