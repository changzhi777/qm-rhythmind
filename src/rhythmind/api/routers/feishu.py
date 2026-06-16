"""
api/routers/feishu.py — 飞书事件回调 Webhook + 消息轮询

端点：
  POST /feishu/webhook    — 飞书事件订阅回调（URL 验证 + 消息接收）
  POST /feishu/poll       — 主动轮询飞书消息（本地开发备选）
  GET  /feishu/status     — 飞书集成状态检查

消息流：
  飞书用户 @机器人 → 飞书回调 → /feishu/webhook
    → 解析消息文本 → HealthRouter.route()
    → Agent 处理 → 回复到飞书会话
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from rhythmind.config import settings

log = structlog.get_logger(__name__)

import shutil

_LARK_CLI_PATH = shutil.which("lark-cli") or "/Users/mac/.npm-global/bin/lark-cli"
_LARK_CLI_EXISTS = bool(_LARK_CLI_PATH)

router = APIRouter(prefix="/feishu", tags=["feishu"])

_known_feishu_users: dict[str, str] = {}


class PollRequest(BaseModel):
    open_id: str | None = None
    chat_id: str | None = None
    limit: int = 10


class PollResponse(BaseModel):
    status: str
    messages: list[dict[str, Any]]
    processed: int


class FeishuStatusResponse(BaseModel):
    enabled: bool
    app_id: str
    bot_name: str | None
    webhook_configured: bool


# ── POST /feishu/webhook ───────────────────────────────────────────────────


@router.post(
    "/webhook",
    summary="飞书事件订阅回调（Webhook）",
    include_in_schema=False,
)
async def feishu_webhook(request: Request, bg: BackgroundTasks) -> dict[str, Any]:
    body = await request.body()
    payload = json.loads(body)

    # 1. URL 验证挑战（飞书配置事件订阅时发送）
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge", "")
        token = payload.get("token", "")
        log.info("feishu.url_verification challenge=%s", challenge[:16])
        return {"challenge": challenge}

    # 2. 验证 Event Token
    event_token = payload.get("token", "")
    if (
        settings.feishu_verification_token
        and event_token != settings.feishu_verification_token
    ):
        log.warning("feishu.invalid_token")
        raise HTTPException(status_code=403, detail="Invalid verification token")

    # 3. 处理事件（后台任务，立即返回 200）
    schema_v2 = payload.get("header", {}).get("schema", "") == "2.0"

    if schema_v2:
        event = payload.get("event", {})
        event_type = payload.get("header", {}).get("event_type", "")
    else:
        event = payload.get("event", {})
        event_type = event.get("type", "")

    if event_type == "im.message.receive_v1" or event_type == "message":
        bg.add_task(_handle_message_event, event, schema_v2)
    else:
        log.info("feishu.unhandled_event type=%s", event_type)

    return {"code": 0, "msg": "ok"}


async def _handle_message_event(event: dict, schema_v2: bool) -> None:
    try:
        if schema_v2:
            sender = event.get("sender", {})
            sender_id = sender.get("sender_id", {}).get("open_id", "")
            msg = event.get("message", {})
        else:
            sender_id = event.get("user_open_id", event.get("user_id", ""))
            msg = event

        message_id = msg.get("message_id", "")
        msg_type = msg.get("message_type", "")
        chat_id = msg.get("chat_id", "")
        content_str = msg.get("content", "{}")

        content = (
            json.loads(content_str) if isinstance(content_str, str) else content_str
        )

        if msg_type == "text":
            text = content.get("text", "").strip()
        elif msg_type == "post":
            content_list = content.get("content", [])
            text_parts = []
            for line in content_list:
                for elem in line:
                    text_parts.append(elem.get("text", ""))
            text = " ".join(text_parts).strip()
        else:
            text = ""

        if not text:
            log.info("feishu.empty_message sender=%s", sender_id)
            return

        log.info(
            "feishu.message_received sender=%s text=%s",
            sender_id,
            text[:80],
        )

        # 将飞书 open_id 映射为系统 user_id
        user_id = _map_feishu_user(sender_id)

        # 路由到 Agent 系统
        reply_text = await _route_to_agent(user_id, text)

        # 回复到飞书
        if message_id and reply_text:
            from rhythmind.integrations.feishu_client import reply_markdown
            from rhythmind.integrations.feishu_client import reply_text as send_reply

            if len(reply_text) > 200:
                await reply_markdown(message_id, reply_text[:4000])
            else:
                await send_reply(message_id, reply_text)

    except Exception as exc:
        log.error("feishu.handle_error error=%s", exc)


def _map_feishu_user(open_id: str) -> str:
    if open_id in _known_feishu_users:
        return _known_feishu_users[open_id]
    user_id = f"feishu_{open_id[:16]}"
    _known_feishu_users[open_id] = user_id
    return user_id


async def _route_to_agent(user_id: str, text: str) -> str:
    try:
        from rhythmind.orchestrator.router import HealthRouter

        hr = HealthRouter()
        session_id = str(uuid.uuid4())
        result = await hr.route(
            user_id=user_id,
            raw_input={"text": text},
            session_id=session_id,
        )

        data = result.data or {}
        if isinstance(data, dict):
            parts = []
            if data.get("summary"):
                parts.append(f"**摘要**: {data['summary']}")
            if data.get("plan"):
                parts.append(f"**计划**: {data['plan']}")
            if data.get("advice"):
                parts.append(f"**建议**: {data['advice']}")
            if data.get("message"):
                parts.append(data["message"])
            return (
                "\n\n".join(parts)
                if parts
                else json.dumps(data, ensure_ascii=False, indent=2)[:2000]
            )

        return str(data)[:2000]

    except Exception as exc:
        log.error("feishu.agent_error error=%s", exc)
        return f"处理请求时出错，请稍后重试。({exc})"


# ── POST /feishu/poll ──────────────────────────────────────────────────────


@router.post(
    "/poll",
    response_model=PollResponse,
    summary="主动轮询飞书消息（本地开发用）",
)
async def poll_feishu_messages(body: PollRequest) -> PollResponse:
    from rhythmind.integrations.feishu_client import (
        get_chat_messages,
        list_bot_chats,
        reply_markdown,
    )
    from rhythmind.integrations.feishu_client import (
        reply_text as send_reply,
    )

    chats = await list_bot_chats(page_size=5)
    chat_id = body.chat_id
    if not chat_id and chats:
        chat_id = chats[0].get("chat_id", "")

    if not chat_id:
        return PollResponse(status="no_chats", messages=[], processed=0)

    messages = await get_chat_messages(
        chat_id=chat_id,
        page_size=body.limit,
    )

    processed = 0
    for msg in messages:
        msg_type = msg.get("msg_type", "")
        body = msg.get("body", {})
        content_str = body.get("content", "{}")
        message_id = msg.get("message_id", "")
        sender = msg.get("sender", {})

        # 跳过机器人自己发的消息
        if sender.get("sender_type") == "app":
            continue

        if msg_type != "text":
            continue

        content = (
            json.loads(content_str) if isinstance(content_str, str) else content_str
        )
        text = content.get("text", "").strip()
        if not text:
            continue

        sender_id = sender.get("id", "")
        chat_id = msg.get("chat_id", "")

        log.info("feishu.poll_message sender=%s text=%s", sender_id, text[:80])

        user_id = _map_feishu_user(sender_id)
        reply_text = await _route_to_agent(user_id, text)

        if message_id and reply_text:
            if len(reply_text) > 200:
                await reply_markdown(message_id, reply_text[:4000])
            else:
                await send_reply(message_id, reply_text)
            processed += 1

    return PollResponse(
        status="success",
        messages=messages,
        processed=processed,
    )


# ── GET /feishu/status ─────────────────────────────────────────────────────


@router.get(
    "/status",
    response_model=FeishuStatusResponse,
    summary="飞书集成状态",
)
async def feishu_status() -> FeishuStatusResponse:
    from rhythmind.integrations.feishu_client import (
        _has_direct_credentials,
        get_bot_info,
    )

    bot_name = None
    webhook_ok = False
    enabled = _has_direct_credentials() or bool(_LARK_CLI_EXISTS)

    try:
        bot_info = await get_bot_info()
        if bot_info:
            bot_name = bot_info.get("app_name")
            webhook_ok = True
    except Exception as exc:
        log.warning("feishu.status_error error=%s", exc)

    return FeishuStatusResponse(
        enabled=enabled,
        app_id="cli_aa885..." if enabled else "",
        bot_name=bot_name,
        webhook_configured=webhook_ok,
    )
