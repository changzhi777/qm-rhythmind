# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/ollama_adapter.py — Ollama HTTP 适配器

主要用途：
  1. PromptAuditor：调用 gemma3:4b 进行本地合规审查
  2. 本地小模型备用推理

接口：Ollama 暴露 OpenAI 兼容的 /api/chat 端点（v0.1.14+）；
     通过 openai.AsyncOpenAI(base_url=ollama_url/v1) 调用，
     无需额外依赖。

连接复用：每个 (base_url, model_name) 组合缓存一个 AsyncOpenAI 实例，
         避免每次请求重建 HTTP 客户端。
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.adapters.model_adapter import ModelAdapter

logger = logging.getLogger(__name__)

# 客户端实例缓存 base_url → AsyncOpenAI
_CLIENT_CACHE: dict[str, Any] = {}


def _get_client(base_url: str, api_key: str = "ollama") -> Any:
    """获取或创建 AsyncOpenAI 客户端（Ollama OpenAI 兼容模式）。"""
    if base_url not in _CLIENT_CACHE:
        from openai import AsyncOpenAI
        _CLIENT_CACHE[base_url] = AsyncOpenAI(
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key=api_key,  # Ollama 不校验 API key，但 SDK 要求非空
        )
    return _CLIENT_CACHE[base_url]


class OllamaAdapter(ModelAdapter):
    """
    Ollama HTTP 本地模型适配器。

    Ollama 从 v0.1.14 起暴露 OpenAI 兼容接口，直接复用 openai.AsyncOpenAI。
    连接到 settings.ollama_base_url（默认 http://localhost:11434）。
    """

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        """
        Args:
            model_name: Ollama 模型名，如 "gemma3:4b"、"qwen2.5:7b"
            base_url:   Ollama 服务地址，None = 读 settings.ollama_base_url
            timeout:    请求超时秒数，None = 读 settings.compliance_audit_timeout
        """
        from rhythmind.config import settings

        self._model_name = model_name
        self._base_url: str = base_url or settings.ollama_base_url
        self._timeout: float = timeout or settings.compliance_audit_timeout

    @property
    def model_id(self) -> str:
        return f"ollama://{self._model_name}"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.1,
        max_tokens: int = 512,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        调用 Ollama OpenAI 兼容接口。

        默认低温（0.1）适合审查类任务；主推理任务调用时传入合适的 temperature。
        """
        import asyncio

        client = _get_client(self._base_url)

        call_kwargs: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            call_kwargs["response_format"] = response_format

        resp = await asyncio.wait_for(
            client.chat.completions.create(**call_kwargs),
            timeout=self._timeout,
        )
        content: str = resp.choices[0].message.content or ""
        logger.debug(
            "ollama_adapter.chat model=%s tokens=%d",
            self._model_name,
            resp.usage.total_tokens if resp.usage else 0,
        )
        return content

    async def health_check(self) -> bool:
        """向 Ollama /api/tags 端点发请求，确认服务存活。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception as e:
            logger.warning("ollama_adapter.health_check failed: %s", e)
            return False
