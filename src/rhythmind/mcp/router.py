# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
mcp/router.py — FastAPI Router：将 MCP SSE 传输层挂载到 /mcp 前缀

挂载路径：
  GET  /mcp/sse         — 客户端建立 SSE 长连接，接收服务器事件
  POST /mcp/messages/   — 客户端通过此端点发送 JSON-RPC 消息

使用场景：
  Claude Code / Claude Desktop 作为 MCP 客户端时，
  在 claude_desktop_config.json 或 .claude 中配置：
    {
      "mcpServers": {
        "rhythmind": {
          "url": "http://localhost:8000/mcp/sse",
          "headers": { "Authorization": "Bearer eyJ..." }
        }
      }
    }

鉴权（v0.1.5+）：
  默认 settings.mcp_require_auth=True 时，两个端点都走 CurrentUserId 依赖；
  ENV=prod 时 assert_production_safe() 强制要求 True。
  仅在受信任本地环境（且明确开关）允许未鉴权访问。

  SseServerTransport 自身的 DNS rebinding 保护（TransportSecurityMiddleware）
  仍然生效，与 JWT 鉴权叠加。

依赖：
  pip install mcp>=1.0
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from mcp.server.sse import SseServerTransport

from rhythmind.api.deps import get_current_user_id
from rhythmind.config import settings
from rhythmind.mcp.server import build_mcp_server

logger = logging.getLogger(__name__)

# ── SSE 传输层（全局单例，管理 session_id → write_stream 映射）────────────────
# endpoint 是客户端 POST 消息时使用的相对路径（含 root_path 前缀时自动拼接）
_sse_transport = SseServerTransport("/mcp/messages/")


# ── 鉴权依赖工厂 ─────────────────────────────────────────────────────────────
# 把"是否需要鉴权"做成依赖工厂，让 mcp_require_auth=False 时端点完全不强制 Bearer。
# 这样 IDE 在本地无 JWT 的连接也能直接用；生产因 assert_production_safe 强制 True。

async def _maybe_authenticated_user(
    request: Request,
) -> str | None:
    """
    若 settings.mcp_require_auth=True 则解析 JWT，否则放行（返回 None）。

    作为 FastAPI 依赖；放在路由签名里就能在生产路径自动开启鉴权。
    """
    if not settings.mcp_require_auth:
        # 仍然在结构化日志里留痕迹，便于审计
        logger.warning(
            "mcp.unauthenticated_access path=%s remote=%s — only safe in local trusted env",  # noqa: E501
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        try:
            from rhythmind.audit import AuditEvent, audit_log
            audit_log(
                AuditEvent.MCP_UNAUTHENTICATED,
                path=request.url.path,
                remote=request.client.host if request.client else "unknown",
            )
        except Exception:
            pass
        return None

    # 复用主鉴权依赖的逻辑：构造 HTTPAuthorizationCredentials 并调用
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header (expected: Bearer <jwt>)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=auth.split(" ", 1)[1]
    )
    return await get_current_user_id(creds)


MCPUserId = Annotated[str | None, Depends(_maybe_authenticated_user)]


# ── APIRouter ─────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/sse")
async def sse_endpoint(
    request: Request,
    user_id: MCPUserId,
) -> StreamingResponse:
    """
    SSE 长连接端点。

    MCP 客户端连接此端点后：
      1. 服务器通过 SSE 流发送初始化消息（endpoint 路径）
      2. 双方建立 JSON-RPC 2.0 通信通道
      3. 客户端通过 POST /mcp/messages/ 发送请求，服务器通过 SSE 推送响应

    每次连接创建独立的 MCP Server 实例（build_mcp_server() 是轻量工厂）。
    """
    logger.info("mcp.sse_connect remote=%s user_id=%s", request.client, user_id)
    mcp_server = build_mcp_server()

    async with _sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,  # noqa: SLF001  # Starlette internal — MCP SDK 约定用法
    ) as (read_stream, write_stream):
        init_options = mcp_server.create_initialization_options()
        await mcp_server.run(read_stream, write_stream, init_options)

    # connect_sse 内部已发送完整响应，此处返回空 Response 仅满足 FastAPI 类型检查
    return Response()  # type: ignore[return-value]


@router.post("/messages/")
async def messages_endpoint(
    request: Request,
    user_id: MCPUserId,
) -> Response:
    """
    客户端消息接收端点。

    客户端通过此端点发送 JSON-RPC 请求（包含 session_id 查询参数），
    SseServerTransport 将消息路由到对应 SSE 会话的 read_stream。
    """
    await _sse_transport.handle_post_message(
        request.scope,
        request.receive,
        request._send,  # noqa: SLF001
    )
    return Response(status_code=202)
