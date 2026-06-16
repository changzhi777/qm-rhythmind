# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/litellm_adapter.py — LiteLLM proxy 适配器

负责所有远端 API 调用：
  OpenAI (gpt-4o / gpt-4.1 / o1)
  Anthropic (claude-3-7-sonnet / claude-sonnet-4-6)
  DeepSeek (deepseek-chat / deepseek-reasoner)
  以及 litellm_config.yaml 中定义的任何别名

透传 HermesBase 现有的 LiteLLM proxy 路径（settings.litellm_base_url），
行为与之前完全一致，只是包装进统一的 ModelAdapter 接口。
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.adapters.model_adapter import ModelAdapter

logger = logging.getLogger(__name__)

# 客户端缓存（base_url + master_key 组合唯一确定一个实例）
_CLIENT_CACHE: dict[str, Any] = {}


def _get_client(base_url: str, api_key: str) -> Any:
    cache_key = f"{base_url}:{api_key}"
    if cache_key not in _CLIENT_CACHE:
        from openai import AsyncOpenAI
        _CLIENT_CACHE[cache_key] = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
    return _CLIENT_CACHE[cache_key]


class LiteLLMAdapter(ModelAdapter):
    """
    LiteLLM proxy 适配器。

    使用 OpenAI 兼容协议连接 LiteLLM proxy，
    model_spec 直接作为 model 参数传递给 proxy。
    """

    def __init__(
        self,
        model_spec: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """
        Args:
            model_spec: LiteLLM proxy 中的模型别名或完整模型名
                        如 "primary"、"fast"、"anthropic/claude-3-7-sonnet-20250219"
            base_url:   LiteLLM proxy URL，None = 读 settings.litellm_base_url
            api_key:    LiteLLM master key，None = 读 settings.litellm_master_key
        """
        from rhythmind.config import settings

        self._model_spec = model_spec
        self._base_url: str = base_url or settings.litellm_base_url
        self._api_key: str = api_key or settings.litellm_master_key

    @property
    def model_id(self) -> str:
        return self._model_spec

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """调用 LiteLLM proxy（与旧版 HermesBase.call_llm 完全等价）。"""
        client = _get_client(self._base_url, self._api_key)

        call_kwargs: dict[str, Any] = {
            "model": self._model_spec,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            call_kwargs["response_format"] = response_format
        call_kwargs.update(kwargs)

        resp = await client.chat.completions.create(**call_kwargs)
        content: str = resp.choices[0].message.content or ""

        logger.debug(
            "litellm_adapter.chat model=%s tokens=%d",
            self._model_spec,
            resp.usage.total_tokens if resp.usage else 0,
        )
        return content

    async def health_check(self) -> bool:
        """调用 LiteLLM /health 端点。"""
        try:
            import httpx
            health_url = self._base_url.rstrip("/v1").rstrip("/") + "/health"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(health_url)
                return resp.status_code == 200
        except Exception as e:
            logger.warning("litellm_adapter.health_check failed: %s", e)
            return False
