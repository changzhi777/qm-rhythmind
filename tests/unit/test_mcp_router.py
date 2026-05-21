"""
tests/unit/test_mcp_router.py — MCP Router 鉴权与路由测试

策略：mock MCP SDK 依赖，测试 _maybe_authenticated_user 鉴权逻辑
和路由端点的基本行为。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rhythmind.mcp.router import _maybe_authenticated_user


class TestMaybeAuthenticatedUser:

    @pytest.mark.asyncio
    async def test_no_auth_required_returns_none(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "mcp_require_auth", False)

        request = MagicMock()
        request.url.path = "/mcp/sse"
        request.client.host = "127.0.0.1"

        result = await _maybe_authenticated_user(request)
        assert result is None

    @pytest.mark.asyncio
    async def test_auth_required_missing_header(self, monkeypatch):
        from fastapi import HTTPException

        from rhythmind.config import settings
        monkeypatch.setattr(settings, "mcp_require_auth", True)

        request = MagicMock()
        request.headers = {}

        with pytest.raises(HTTPException) as exc_info:
            await _maybe_authenticated_user(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_required_malformed_header(self, monkeypatch):
        from fastapi import HTTPException

        from rhythmind.config import settings
        monkeypatch.setattr(settings, "mcp_require_auth", True)

        request = MagicMock()
        request.headers = {"authorization": "Basic abc123"}

        with pytest.raises(HTTPException) as exc_info:
            await _maybe_authenticated_user(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_required_valid_bearer(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "mcp_require_auth", True)

        request = MagicMock()
        request.headers = {"authorization": "Bearer valid.jwt.token"}

        with patch("rhythmind.mcp.router.get_current_user_id") as mock_get:
            mock_get.return_value = "user123"
            result = await _maybe_authenticated_user(request)

        assert result == "user123"
