# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_request_size.py — RequestSizeLimitMiddleware 单元测试

覆盖 line 53/60-61/78-85 7 行 missing：
- max_bytes=0 禁用检查
- Content-Length 非数字容错（不抛）
- chunked 无 Content-Length 时流式读 body + 超限拒绝
- chunked 路径仅对 POST/PUT/PATCH 生效

测试策略：构造 fake Request（带可控 headers / receive）和 call_next mock，
直接调 middleware.dispatch()。
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from starlette.requests import Request

from rhythmind.api.middleware.request_size import RequestSizeLimitMiddleware


def _make_request(
    method: str = "POST",
    headers: dict[str, str] | None = None,
    body: bytes = b"",
) -> Request:
    """构造可控的 starlette Request（带 headers + body）。"""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    # 合并 headers（确保 host 存在以构造有效 Request）
    base_headers = {"host": "testserver"}
    if headers:
        base_headers.update(headers)
    # Content-Length 应由调用方显式传（这里不自动计算，便于测试边界）

    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in base_headers.items()],
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
    }
    return Request(scope, receive=receive)


class TestMaxBytesDisabled:
    """max_bytes <= 0 时整个检查跳过（line 53）。"""

    @pytest.mark.asyncio
    async def test_max_bytes_zero_skips_check_and_passes(self):
        """max_bytes=0 时即使 Content-Length 超大也直接通过（不检查）。"""
        middleware = RequestSizeLimitMiddleware(app=None, max_bytes=0)
        # 故意构造 Content-Length 100MB（远超大）—— 但 max_bytes=0 应跳过
        request = _make_request(
            method="POST",
            headers={"content-length": "100000000"},
            body=b"x" * 1_000_000,  # 1MB body
        )
        call_next_called = []

        async def call_next(req):
            call_next_called.append(req)
            return "NEXT_RESPONSE"

        result = await middleware.dispatch(request, call_next)
        assert result == "NEXT_RESPONSE"
        assert len(call_next_called) == 1


class TestContentLengthFastPath:
    """Content-Length 快速拒绝（line 60-61 容错 + line 62-72 reject）。"""

    @pytest.mark.asyncio
    async def test_invalid_content_length_treated_as_zero(self):
        """Content-Length 为非数字时不应抛异常，按 length=0 处理。"""
        middleware = RequestSizeLimitMiddleware(app=None, max_bytes=1000)
        request = _make_request(
            method="POST",
            headers={"content-length": "not-a-number"},
            body=b"x" * 100,  # 真实 body 100 字节
        )

        async def call_next(req):
            return "NEXT"

        result = await middleware.dispatch(request, call_next)
        # 非数字 Content-Length → length=0 → 不超限 → 通过
        assert result == "NEXT"


class TestChunkedBodyCheck:
    """chunked/无 Content-Length 路径（line 78-85）。"""

    @pytest.mark.asyncio
    async def test_chunked_post_within_limit_passes(self):
        """POST 无 Content-Length + body 不超限 → 通过。"""
        middleware = RequestSizeLimitMiddleware(app=None, max_bytes=1000)
        # 无 content-length 头
        request = _make_request(
            method="POST",
            headers={},  # 故意不加 content-length
            body=b"x" * 100,
        )

        async def call_next(req):
            return "OK"

        result = await middleware.dispatch(request, call_next)
        assert result == "OK"

    @pytest.mark.asyncio
    async def test_chunked_post_exceeds_limit_returns_413(self):
        """POST 无 Content-Length + body 超限 → 413 + 降级 JSONResponse。"""
        middleware = RequestSizeLimitMiddleware(app=None, max_bytes=100)
        request = _make_request(
            method="POST",
            headers={},  # 无 content-length
            body=b"x" * 200,  # 超过 100
        )

        async def call_next(req):
            pytest.fail("call_next 不应被调用，超限应直接返回 413")

        result = await middleware.dispatch(request, call_next)
        assert result.status_code == 413
        body = json.loads(result.body)
        assert "too large" in body["detail"]
        assert "100" in body["detail"]  # 限值出现在 detail 中

    @pytest.mark.asyncio
    async def test_chunked_only_for_post_put_patch(self):
        """无 Content-Length 时 chunked 检查仅对 POST/PUT/PATCH 生效（GET 跳过）。"""
        middleware = RequestSizeLimitMiddleware(app=None, max_bytes=100)
        # GET 请求无 Content-Length，body 超大也不应被检查（直接通过）
        request = _make_request(
            method="GET",
            headers={},
            body=b"x" * 200,
        )

        async def call_next(req):
            return "GET_PASSED"

        result = await middleware.dispatch(request, call_next)
        assert result == "GET_PASSED"
