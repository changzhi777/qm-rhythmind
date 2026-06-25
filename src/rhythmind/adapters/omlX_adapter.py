# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/omlX_adapter.py — oMLX 本地模型服务适配器

主要用途：
  1. 本地 LLM 服务（gemma-4-e4b-it-4bit 等）
  2. 替代 Ollama 的本地推理方案

接口：oMLX 暴露 OpenAI 兼容的 /v1/chat/completions 端点。
      通过 openai.AsyncOpenAI(base_url=<omlX_url>/v1) 调用。

连接复用：每个 (base_url, model_name) 组合缓存一个 AsyncOpenAI 实例，
         避免每次请求重建 HTTP 客户端。
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.adapters.model_adapter import ModelAdapter

logger = logging.getLogger(__name__)

# 客户端实例缓存 base_url+timeout → AsyncOpenAI
_CLIENT_CACHE: dict[tuple[str, float], Any] = {}


def _get_client(base_url: str, api_key: str, timeout: float = 60.0) -> Any:
    """获取或创建 AsyncOpenAI 客户端（oMLX OpenAI 兼容模式）。

    2026-06-25: 显式设置 httpx 超时,避免 OpenAI SDK 默认 60s 限制 gemma-4 长 prompt 推理。
    """
    cache_key = (base_url, timeout)
    if cache_key not in _CLIENT_CACHE:
        import httpx
        from openai import AsyncOpenAI

        _CLIENT_CACHE[cache_key] = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key=api_key,
            timeout=httpx.Timeout(timeout),
        )
    return _CLIENT_CACHE[cache_key]


class OMLXTimeoutError(Exception):
    """
    oMLX 推理超时异常。

    区别于通用 TimeoutError，调用方可以：
      - try/except OMLXTimeoutError → 走 fallback_report
      - try/except (asyncio.TimeoutError, OMLXTimeoutError) → 同时兜底
    """
    pass


class OMLXAdapter(ModelAdapter):
    """
    oMLX 本地模型服务适配器。

    oMLX 是本地 LLM 服务（类似 Ollama），通过 HTTP API 提供 OpenAI 兼容接口。
    连接到 settings.omlX_base_url（默认 http://localhost:8000）。
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """
        Args:
            model_name: oMLX 模型名，如 "gemma-4-e4b-it-4bit"、"qwen2.5:7b"
            base_url:   oMLX 服务地址，None = 读 settings.omlX_base_url
            api_key:    oMLX API 鉴权 key，None = 读 settings.omlX_api_key
            timeout:    请求超时秒数，None = 读 settings.compliance_audit_timeout
        """
        from rhythmind.config import settings

        self._model_name = model_name
        self._base_url: str = base_url or settings.omlX_base_url
        self._api_key: str = api_key or settings.omlX_api_key
        # 默认 omlX_chat_timeout（主模型 60s），合规审查方显式传 audit_timeout（8s）
        self._timeout: float = timeout or settings.omlX_chat_timeout

    @property
    def model_id(self) -> str:
        return f"omlX://{self._model_name}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        调用 oMLX OpenAI 兼容接口。

        超时降级：内部 asyncio.wait_for 触发时，把 asyncio.TimeoutError
        转换为 oMLXTimeoutError 上抛，调用方（agent 层）走 fallback 路径。
        与 PromptAuditor 的 fallback=PASS 行为不同——主模型必须显式失败
        让 agent 用降级报告，避免静默生成空内容。
        """
        import asyncio

        client = _get_client(self._base_url, self._api_key, timeout=self._timeout)

        call_kwargs: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            call_kwargs["response_format"] = response_format

        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(**call_kwargs),
                timeout=self._timeout,
            )
        except TimeoutError as e:
            logger.warning(
                "omlX_adapter.timeout model=%s after=%.1fs — raising OMLXTimeoutError",
                self._model_name, self._timeout,
            )
            raise OMLXTimeoutError(
                f"oMLX {self._model_name} 推理超时（{self._timeout:.0f}s）"
            ) from e

        content: str = resp.choices[0].message.content or ""
        logger.debug(
            "omlX_adapter.chat model=%s tokens=%d",
            self._model_name,
            resp.usage.total_tokens if resp.usage else 0,
        )
        return content

    async def health_check(self) -> bool:
        """向 oMLX /v1/models 端点发请求，确认服务存活。"""
        try:
            import httpx

            _get_client(self._base_url, self._api_key)
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(
                    f"{self._base_url.rstrip('/')}/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.warning("omlX_adapter.health_check failed: %s", e)
            return False