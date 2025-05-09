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
          "url": "http://localhost:8000/mcp/sse"
        }
      }
    }

安全说明：
  SseServerTransport 内置 DNS rebinding 保护（TransportSecurityMiddleware）。
  生产环境建议在 /mcp/sse 前加 JWT 认证中间件，此 Router 本身不做认证。

依赖：
  pip install mcp>=1.0
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from mcp.server.sse import SseServerTransport

from rhythmind.mcp.server import build_mcp_server

logger = logging.getLogger(__name__)

# ── SSE 传输层（全局单例，管理 session_id → write_stream 映射）────────────────
# endpoint 是客户端 POST 消息时使用的相对路径（含 root_path 前缀时自动拼接）
_sse_transport = SseServerTransport("/mcp/messages/")

# ── APIRouter ─────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    """
    SSE 长连接端点。

    MCP 客户端连接此端点后：
      1. 服务器通过 SSE 流发送初始化消息（endpoint 路径）
      2. 双方建立 JSON-RPC 2.0 通信通道
      3. 客户端通过 POST /mcp/messages/ 发送请求，服务器通过 SSE 推送响应

    每次连接创建独立的 MCP Server 实例（build_mcp_server() 是轻量工厂）。
    """
    logger.info("mcp.sse_connect remote=%s", request.client)
    mcp_server = build_mcp_server()

    async with _sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,  # noqa: SLF001  # Starlette internal — MCP SDK 约定用法
    ) as (read_stream, write_stream):
        init_options = mcp_server.create_initialization_options()
        await mcp_server.run(read_stream, write_stream, init_options)

    # connect_sse 内部已向客户端发送完整响应，此处返回空 Response 仅满足 FastAPI 类型检查
    return Response()  # type: ignore[return-value]


@router.post("/messages/")
async def messages_endpoint(request: Request) -> Response:
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
