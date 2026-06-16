"""
tests/unit/test_feishu.py — 飞书 Webhook / Poll / Status 路由测试

覆盖：
  POST /feishu/webhook
    ① URL 验证挑战（type=url_verification）→ 返回 challenge
    ② 错误 verification token → 403
    ③ v1 schema 消息事件（im.message.receive_v1）→ 后台处理
    ④ v2 schema 消息事件（schema="2.0"）→ 后台处理
    ⑤ 未处理事件类型 → 返回 ok 不入队
    ⑥ 缺少 token 字段 → 200 ok

  POST /feishu/poll
    ⑦ 无 chat 且无 bot chats → 返回 status="no_chats"
    ⑧ 有 chat 时拉取并处理消息

  GET /feishu/status
    ⑨ 默认状态返回（含 enabled/app_id 字段）

策略：使用 httpx ASGITransport 绑定到 app，外部依赖（feishu_client / HealthRouter）通过
monkeypatch 替换为 AsyncMock / MagicMock，测试路由自身的鉴权/分支逻辑。
"""
from __future__ import annotations

import os

# 必须在 import rhythmind 之前注入 env
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEV_AUTH_BYPASS", "true")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "feishu-test-secret-32-chars-min!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-feishu-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client(monkeypatch):
    """返回绑定到 FastAPI app 的 AsyncClient，并 mock 掉飞书外部依赖。"""

    # ── Mock rhythmind.integrations.feishu_client（按需 import）────────
    from rhythmind.integrations import feishu_client as fc

    # 用 monkeypatch.setattr 注入（pytest 测试结束时自动 undo，避免污染其他测试）
    monkeypatch.setattr(
        fc, "list_bot_chats", _AsyncMagic(return_value=[]), raising=True,
    )
    monkeypatch.setattr(
        fc, "get_chat_messages", _AsyncMagic(return_value=[]), raising=True,
    )
    monkeypatch.setattr(
        fc, "get_bot_info", _AsyncMagic(return_value={"app_name": "TestBot"}),
        raising=True,
    )
    monkeypatch.setattr(
        fc, "_has_direct_credentials", lambda: False, raising=True,
    )
    monkeypatch.setattr(
        fc, "reply_text", _AsyncMagic(return_value=None), raising=True,
    )
    monkeypatch.setattr(
        fc, "reply_markdown", _AsyncMagic(return_value=None), raising=True,
    )

    # ── Mock HealthRouter（飞书路由内部按需 import）──────────────────────
    from rhythmind.orchestrator import router as orch_router

    class _StubResult:
        data = {"summary": "好的，已记录。", "advice": "继续保持。"}

    monkeypatch.setattr(
        orch_router, "HealthRouter",
        lambda: _StubRouter(_StubResult()),
        raising=True,
    )

    # ── Mock LARK CLI 检测（避免在 CI 中真实探测）────────────────────────
    import rhythmind.api.routers.feishu as feishu_router_mod
    monkeypatch.setattr(feishu_router_mod, "_LARK_CLI_EXISTS", False, raising=True)

    # ── ASGI 客户端 ─────────────────────────────────────────────────────
    from rhythmind.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class _AsyncMagic:
    """最小 AsyncMock 替代品：调用即返回预设值，await 透明。"""

    def __init__(self, return_value=None):
        self.return_value = return_value
        self.call_count = 0

    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        return self.return_value


class _StubRouter:
    def __init__(self, result):
        self._result = result

    async def route(self, **kwargs):
        return self._result


def _make_async_mock(return_value=None):
    return _AsyncMagic(return_value=return_value)


# ── /feishu/webhook ─────────────────────────────────────────────────────────


class TestFeishuWebhook:
    """POST /feishu/webhook — URL 验证 + 消息接收。"""

    @pytest.mark.asyncio
    async def test_url_verification_returns_challenge(self, app_client):
        """① URL 验证挑战（type=url_verification）→ 返回 challenge 字段。"""
        resp = await app_client.post(
            "/api/v1/feishu/webhook",
            json={
                "type": "url_verification",
                "challenge": "abc123-challenge-xyz",
                "token": "",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"challenge": "abc123-challenge-xyz"}

    @pytest.mark.asyncio
    async def test_invalid_token_returns_403(self, app_client, monkeypatch):
        """② 配置了 feishu_verification_token 且 event token 不匹配 → 403。"""
        from rhythmind.config import settings

        monkeypatch.setattr(settings, "feishu_verification_token", "expected-token")
        try:
            resp = await app_client.post(
                "/api/v1/feishu/webhook",
                json={
                    "type": "event_callback",
                    "token": "wrong-token",
                    "event": {"type": "unknown"},
                },
            )
            assert resp.status_code == 403
            assert "Invalid verification token" in resp.text
        finally:
            monkeypatch.setattr(settings, "feishu_verification_token", "")

    @pytest.mark.asyncio
    async def test_v1_message_event_dispatched(self, app_client):
        """③ v1 schema 消息事件（im.message.receive_v1）→ 后台调度 + 200 ok。"""
        resp = await app_client.post(
            "/api/v1/feishu/webhook",
            json={
                "type": "event_callback",
                "token": "",
                "event": {
                    "type": "im.message.receive_v1",
                    "user_open_id": "ou_test_user_001",
                    "message_id": "om_v1_msg_001",
                    "chat_id": "oc_chat_001",
                    "message_type": "text",
                    "content": json_dumps({"text": "你好机器人"}),
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"code": 0, "msg": "ok"}

    @pytest.mark.asyncio
    async def test_v2_schema_message_event_dispatched(self, app_client):
        """④ v2 schema（schema="2.0"）→ 同样进入消息处理分支。"""
        resp = await app_client.post(
            "/api/v1/feishu/webhook",
            json={
                "schema": "2.0",
                "header": {
                    "event_type": "im.message.receive_v1",
                    "app_id": "cli_aa885",
                },
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_v2_user"}},
                    "message": {
                        "message_id": "om_v2_msg_001",
                        "chat_id": "oc_chat_v2",
                        "message_type": "text",
                        "content": json_dumps({"text": "v2 消息"}),
                    },
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_unhandled_event_type_returns_ok(self, app_client):
        """⑤ 未处理事件类型 → 200 ok 但不入队消息处理。"""
        resp = await app_client.post(
            "/api/v1/feishu/webhook",
            json={
                "type": "event_callback",
                "token": "",
                "event": {"type": "im.chat.member_added_v1"},
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"code": 0, "msg": "ok"}

    @pytest.mark.asyncio
    async def test_event_callback_without_token_ok_when_token_unset(self, app_client):
        """⑥ 未配置 verification_token 时，event_callback 缺少 token 字段也接受。"""
        from rhythmind.config import settings

        original = settings.feishu_verification_token
        try:
            settings.feishu_verification_token = ""
            resp = await app_client.post(
                "/api/v1/feishu/webhook",
                json={
                    "type": "event_callback",
                    "event": {"type": "app_open"},
                },
            )
            assert resp.status_code == 200
        finally:
            settings.feishu_verification_token = original


# ── /feishu/poll ────────────────────────────────────────────────────────────


class TestFeishuPoll:
    """POST /feishu/poll — 主动轮询飞书消息。"""

    @pytest.mark.asyncio
    async def test_poll_without_chat_returns_no_chats(self, app_client):
        """⑦ 无 chat_id 且 list_bot_chats 为空 → status="no_chats"。"""
        resp = await app_client.post(
            "/api/v1/feishu/poll",
            json={"limit": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "no_chats"
        assert body["messages"] == []
        assert body["processed"] == 0

    @pytest.mark.asyncio
    async def test_poll_with_chat_id_returns_empty_messages(self, app_client):
        """⑧ 显式提供 chat_id + get_chat_messages 返回空 → processed=0 status="success"。"""  # noqa: E501
        # 重写 get_chat_messages mock 让它返回空
        # 通过 app_client 的 monkeypatch 上下文已注入；额外再覆盖一次
        from unittest.mock import AsyncMock

        from rhythmind.integrations import feishu_client as fc
        fc.get_chat_messages = AsyncMock(return_value=[])

        resp = await app_client.post(
            "/api/v1/feishu/poll",
            json={"chat_id": "oc_explicit_chat", "limit": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["processed"] == 0
        assert body["messages"] == []


# ── /feishu/status ──────────────────────────────────────────────────────────


class TestFeishuStatus:
    """GET /feishu/status — 飞书集成状态。"""

    @pytest.mark.asyncio
    async def test_status_returns_expected_shape(self, app_client):
        """⑨ 返回 enabled / app_id / bot_name / webhook_configured 字段。"""
        resp = await app_client.get("/api/v1/feishu/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "enabled" in body
        assert "app_id" in body
        assert "bot_name" in body
        assert "webhook_configured" in body
        # 默认 mock：_LARK_CLI_EXISTS=False 且无直接凭证 → enabled=False
        assert body["enabled"] is False
        assert body["app_id"] == ""
        # get_bot_info mock 返回 {"app_name": "TestBot"}
        assert body["bot_name"] == "TestBot"
        # bot_info 成功 → webhook_configured=True（_get_bot_info 不抛异常）
        assert body["webhook_configured"] is True


# ── Helper ──────────────────────────────────────────────────────────────────


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
