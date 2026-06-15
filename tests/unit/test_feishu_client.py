"""
tests/unit/test_feishu_client.py — 飞书 API 客户端单测

覆盖：
  - _has_direct_credentials (纯函数)
  - _get_tenant_token_direct (mock httpx)
  - send_text_message (mock _cli_api)
  - reply_text (mock httpx)
  - get_bot_info (mock _cli_api)
  - _token_cache 缓存逻辑
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import rhythmind.integrations.feishu_client as fc


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """每个测试前重置 _token_cache（避免跨测试污染）。"""
    fc._token_cache["token"] = ""
    fc._token_cache["expires_at"] = 0.0
    yield
    fc._token_cache["token"] = ""
    fc._token_cache["expires_at"] = 0.0


class TestHasDirectCredentials:
    def test_both_configured_returns_true(self, monkeypatch):
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret_xyz")
        assert fc._has_direct_credentials() is True

    def test_missing_app_id_returns_false(self, monkeypatch):
        monkeypatch.setattr(fc.settings, "feishu_app_id", "")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")
        assert fc._has_direct_credentials() is False

    def test_missing_app_secret_returns_false(self, monkeypatch):
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "")
        assert fc._has_direct_credentials() is False

    def test_both_missing_returns_false(self, monkeypatch):
        monkeypatch.setattr(fc.settings, "feishu_app_id", "")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "")
        assert fc._has_direct_credentials() is False


class TestGetTenantTokenDirect:
    @pytest.mark.asyncio
    async def test_successful_token_response(self, monkeypatch):
        """成功响应：缓存 token 并返回。"""
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0,
            "msg": "ok",
            "tenant_access_token": "t-abc123",
            "expire": 7200,
        }

        with patch.object(fc.httpx, "AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            token = await fc._get_tenant_token_direct()
            assert token == "t-abc123"
            assert fc._token_cache["token"] == "t-abc123"
            assert fc._token_cache["expires_at"] > 0

    @pytest.mark.asyncio
    async def test_error_code_raises_runtime_error(self, monkeypatch):
        """code != 0 抛 RuntimeError。"""
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"code": 999, "msg": "invalid credentials"}

        with patch.object(fc.httpx, "AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RuntimeError, match="invalid credentials"):
                await fc._get_tenant_token_direct()

    @pytest.mark.asyncio
    async def test_uses_cached_token_when_valid(self, monkeypatch):
        """缓存未过期时直接返回缓存 token（不调 API）。"""
        import time
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")
        fc._token_cache["token"] = "cached-token-xyz"
        fc._token_cache["expires_at"] = time.time() + 3600  # 1h 后过期

        with patch.object(fc.httpx, "AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock()
            mock_client_cls.return_value = mock_client

            token = await fc._get_tenant_token_direct()
            assert token == "cached-token-xyz"
            mock_client.post.assert_not_called()


class TestGetTenantTokenAutoSelect:
    @pytest.mark.asyncio
    async def test_direct_path_when_credentials_configured(self, monkeypatch):
        """有凭证时走直连模式。"""
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")

        with patch.object(fc, "_get_tenant_token_direct", new=AsyncMock(return_value="direct-token")) as mock_direct:
            with patch.object(fc, "_get_tenant_token_via_cli", new=AsyncMock()) as mock_cli:
                token = await fc._get_tenant_token()
                assert token == "direct-token"
                mock_direct.assert_awaited_once()
                mock_cli.assert_not_called()

    @pytest.mark.asyncio
    async def test_cli_fallback_when_no_credentials(self, monkeypatch):
        """无凭证时回退 lark-cli 模式。"""
        monkeypatch.setattr(fc.settings, "feishu_app_id", "")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "")

        with patch.object(fc, "_get_tenant_token_direct", new=AsyncMock()) as mock_direct:
            with patch.object(fc, "_get_tenant_token_via_cli", new=AsyncMock(return_value="cli-token")) as mock_cli:
                token = await fc._get_tenant_token()
                assert token == "cli-token"
                mock_direct.assert_not_called()
                mock_cli.assert_awaited_once()


class TestApiHeaders:
    @pytest.mark.asyncio
    async def test_returns_bearer_and_content_type(self):
        """_api_headers 包含 Bearer + Content-Type。"""
        with patch.object(fc, "_get_tenant_token", new=AsyncMock(return_value="t-xyz")):
            headers = await fc._api_headers()
            assert headers["Authorization"] == "Bearer t-xyz"
            assert headers["Content-Type"] == "application/json"


class TestSendTextMessage:
    @pytest.mark.asyncio
    async def test_delegates_to_cli_api_with_correct_path(self):
        """send_text_message 调用 _cli_api POST /open-apis/im/v1/messages，payload 正确。"""
        expected_response = {"code": 0, "msg": "ok", "data": {"message_id": "om_123"}}
        with patch.object(fc, "_cli_api", new=AsyncMock(return_value=expected_response)) as mock_cli:
            result = await fc.send_text_message(receive_id="ou_user1", text="Hello 飞书")
            assert result == expected_response
            mock_cli.assert_awaited_once()
            call_args = mock_cli.await_args
            assert call_args.args[0] == "POST"
            assert call_args.args[1] == "/open-apis/im/v1/messages"
            payload = call_args.kwargs["data"]
            assert payload["receive_id"] == "ou_user1"
            assert payload["receive_id_type"] == "open_id"
            assert payload["msg_type"] == "text"
            # content 是 JSON 字符串
            content = json.loads(payload["content"])
            assert content["text"] == "Hello 飞书"

    @pytest.mark.asyncio
    async def test_supports_chat_id_receive_id_type(self):
        """receive_id_type 设为 chat_id 时正确传递。"""
        with patch.object(fc, "_cli_api", new=AsyncMock(return_value={"code": 0})):
            await fc.send_text_message(
                receive_id="oc_chat1", text="群消息", receive_id_type="chat_id",
            )
            payload = fc._cli_api.await_args.kwargs["data"]
            assert payload["receive_id_type"] == "chat_id"
            assert payload["receive_id"] == "oc_chat1"


class TestReplyText:
    @pytest.mark.asyncio
    async def test_uses_httpx_post_to_reply_endpoint(self):
        """reply_text 用 httpx 直连 POST /im/v1/messages/{id}/reply。"""
        monkeypatch_response = MagicMock()
        monkeypatch_response.json.return_value = {"code": 0, "msg": "ok", "data": {"message_id": "om_reply"}}

        with patch.object(fc, "_get_tenant_token", new=AsyncMock(return_value="t-xyz")):
            with patch.object(fc.httpx, "AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.post = AsyncMock(return_value=monkeypatch_response)
                mock_client_cls.return_value = mock_client

                result = await fc.reply_text(message_id="om_in_1", text="回复内容")
                assert result["code"] == 0

                # 验证 URL 和 payload
                call_args = mock_client.post.await_args
                assert "om_in_1/reply" in call_args.args[0]
                payload = call_args.kwargs["json"]
                assert payload["msg_type"] == "text"
                # content 是 JSON 字符串
                content = json.loads(payload["content"])
                assert content["text"] == "回复内容"


class TestGetBotInfo:
    @pytest.mark.asyncio
    async def test_delegates_to_cli_api(self):
        """get_bot_info 通过 _cli_api 调 /open-apis/bot/v3/info，提取 bot 字段。"""
        cli_response = {"code": 0, "bot": {"app_name": "TestBot"}}
        expected_bot = {"app_name": "TestBot"}
        with patch.object(fc, "_cli_api", new=AsyncMock(return_value=cli_response)):
            result = await fc.get_bot_info()
            assert result == expected_bot
            fc._cli_api.assert_awaited_once_with("GET", "/open-apis/bot/v3/info")


class TestTokenCacheExpiry:
    """_token_cache 提前 5 分钟刷新逻辑验证。"""

    @pytest.mark.asyncio
    async def test_expire_minus_300_buffer(self, monkeypatch):
        """expiry = time.time() + (server_expire - 300)。"""
        import time
        monkeypatch.setattr(fc.settings, "feishu_app_id", "cli_aa885")
        monkeypatch.setattr(fc.settings, "feishu_app_secret", "secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": 0, "tenant_access_token": "t-abc", "expire": 7200,
        }

        with patch.object(fc.httpx, "AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            t_before = time.time()
            await fc._get_tenant_token_direct()
            t_after = time.time()

            # expires_at 应该是 (t_before + 7200 - 300) 到 (t_after + 7200 - 300) 之间
            expected_min = t_before + 7200 - 300
            expected_max = t_after + 7200 - 300
            assert expected_min <= fc._token_cache["expires_at"] <= expected_max
