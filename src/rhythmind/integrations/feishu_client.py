"""
integrations/feishu_client.py — 飞书 API 客户端

通过 lark-cli 子进程调用飞书 API，复用已有的 OAuth 认证。
也可通过 httpx 直接调用（需配置 FEISHU_APP_ID/SECRET）。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from typing import Any, cast

import httpx
import structlog

from rhythmind.config import settings

log = structlog.get_logger(__name__)

_BASE = "https://open.feishu.cn/open-apis"
_LARK_CLI = shutil.which("lark-cli") or "/Users/mac/.npm-global/bin/lark-cli"

_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


def _has_direct_credentials() -> bool:
    return bool(settings.feishu_app_id and settings.feishu_app_secret)


async def _get_tenant_token() -> str:
    if _has_direct_credentials():
        return await _get_tenant_token_direct()

    return await _get_tenant_token_via_cli()


async def _get_tenant_token_direct() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return cast(str, _token_cache["token"])

    async with httpx.AsyncClient(timeout=10) as cli:
        resp = await cli.post(
            f"{_BASE}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
        )
        data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"Feishu token error: {data.get('msg')}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expire", 7200) - 300
    return cast(str, _token_cache["token"])


async def _get_tenant_token_via_cli() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return cast(str, _token_cache["token"])

    proc = await asyncio.create_subprocess_exec(
        _LARK_CLI, "api", "POST", "/open-apis/auth/v3/tenant_access_token/internal",
        "--as", "bot", "--format", "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    data = json.loads(stdout)

    if data.get("code") != 0:
        raise RuntimeError(f"Feishu CLI token error: {data.get('msg')}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expire", 7200) - 300
    log.info("feishu.token_refreshed via lark-cli")
    return cast(str, _token_cache["token"])


async def _api_headers() -> dict[str, str]:
    token = await _get_tenant_token()
    return cast(
        dict[str, str],
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )


async def _cli_api(method: str, path: str, data: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    args = [_LARK_CLI, "api", method, path, "--as", "bot", "--format", "json"]
    if data:
        args.extend(["--data", json.dumps(data)])
    if params:
        args.extend(["--params", json.dumps(params)])

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    if proc.returncode != 0 or not stdout.strip():
        log.error("feishu.cli_error rc=%s stderr=%s", proc.returncode, stderr.decode()[:200])
        return {"code": -1, "msg": "CLI call failed"}
    return cast(dict[str, Any], json.loads(stdout))


async def send_text_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    return await _cli_api(
        "POST", "/open-apis/im/v1/messages",
        data={
            "receive_id": receive_id,
            "receive_id_type": receive_id_type,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
    )


async def reply_text(message_id: str, text: str) -> dict[str, Any]:
    headers = await _api_headers()
    async with httpx.AsyncClient(timeout=10) as cli:
        resp = await cli.post(
            f"{_BASE}/im/v1/messages/{message_id}/reply",
            headers=headers,
            json={
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )
        return cast(dict[str, Any], resp.json())


async def reply_markdown(message_id: str, content: str) -> dict[str, Any]:
    headers = await _api_headers()
    async with httpx.AsyncClient(timeout=10) as cli:
        resp = await cli.post(
            f"{_BASE}/im/v1/messages/{message_id}/reply",
            headers=headers,
            json={
                "msg_type": "interactive",
                "content": json.dumps({
                    "config": {"wide_screen_mode": True},
                    "header": {
                        "title": {"tag": "plain_text", "content": "RHYTHMIND 律动"},
                        "template": "turquoise",
                    },
                    "elements": [{"tag": "markdown", "content": content}],
                }),
            },
        )
        return cast(dict[str, Any], resp.json())


async def list_bot_chats(page_size: int = 20) -> list[dict[str, Any]]:
    data = await _cli_api(
        "GET", "/open-apis/im/v1/chats",
    )
    if data.get("code") != 0:
        log.error("feishu.list_chats_failed code=%s msg=%s", data.get("code"), data.get("msg"))
        return []

    items = data.get("data", {}).get("items", [])

    if data["data"].get("has_more") and not items:
        data2 = await _cli_api("GET", "/open-apis/im/v1/chats?user_id_type=open_id&page_size=50")
        items = data2.get("data", {}).get("items", [])

    return cast(list[dict[str, Any]], items)


async def get_chat_messages(
    chat_id: str,
    page_size: int = 20,
    start_time: str | None = None,
) -> list[dict[str, Any]]:
    params = {"container_id_type": "chat", "container_id": chat_id, "page_size": str(page_size)}
    if start_time:
        params["start_time"] = start_time

    data = await _cli_api("GET", "/open-apis/im/v1/messages", params=params)
    if data.get("code") != 0:
        log.error("feishu.get_messages_failed code=%s msg=%s", data.get("code"), data.get("msg"))
        return []

    return cast(list[dict[str, Any]], data.get("data", {}).get("items", []))


async def get_bot_info() -> dict[str, Any]:
    data = await _cli_api("GET", "/open-apis/bot/v3/info")
    return cast(dict[str, Any], data.get("bot", {}))
