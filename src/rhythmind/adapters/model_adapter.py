# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/model_adapter.py — ModelAdapter 抽象基类

所有 LLM 后端适配器的统一接口：
  MLXAdapter     — Apple Silicon 本地推理（mlx-lm 直接 API）
  OllamaAdapter  — Ollama HTTP 服务（本地合规审查 / 小模型）
  LiteLLMAdapter — LiteLLM proxy（远端 API：OpenAI / Anthropic / DeepSeek 等）

调用方（HermesBase.call_llm / PromptAuditor）只依赖本接口，
对底层实现完全透明。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class ModelAdapter(ABC):
    """
    LLM 适配器抽象接口。

    实现要求：
      - chat()  必须实现，返回完整生成文本（str）
      - stream() 可选实现，返回 token 流；默认实现调 chat() 一次性返回
      - health_check() 可选，默认返回 True
    """

    # ── 必须实现 ──────────────────────────────────────────────────────────

    @abstractmethod
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
        同步语义的 LLM 调用（内部可以是 async 或 to_thread 包装）。

        Args:
            messages:        OpenAI 格式 messages 列表
            temperature:     采样温度
            max_tokens:      最大输出 token 数
            response_format: {"type": "json_object"} 等
            **kwargs:        适配器特定参数

        Returns:
            模型输出文本（已去掉 <think> 标签等包装）
        """

    @property
    @abstractmethod
    def model_id(self) -> str:
        """标识本适配器的完整 model_spec 字符串，如 mlx://mlx-community/Qwen3-30B-A3B-4bit。"""

    # ── 可选实现 ──────────────────────────────────────────────────────────

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        流式返回 token。

        默认降级为 chat() 一次性返回（适配器若不支持真实流式）。
        子类可覆盖以实现真实流式输出。
        """
        result = await self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        yield result

    async def health_check(self) -> bool:
        """
        检查适配器是否可用（依赖服务是否运行 / 模型文件是否存在）。

        默认返回 True（乐观假设）；子类应覆盖以做真实检查。
        """
        return True
