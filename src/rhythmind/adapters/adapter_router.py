# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
adapters/adapter_router.py — Model Adapter 路由层

根据 model_spec 前缀选择对应的 ModelAdapter 实现：

  "mlx://<hf_repo_or_local_path>"  → MLXAdapter
  "ollama://<model_name>"          → OllamaAdapter
  其他任何字符串                    → LiteLLMAdapter

Adapter 实例缓存：同一 model_spec 只创建一个 Adapter 实例（轻量对象）。
MLXAdapter 的模型文件通过 _MODEL_CACHE 在进程级缓存（详见 mlx_adapter.py）。

使用示例：
  from rhythmind.adapters.adapter_router import adapter_router

  # 调用主模型（取 settings.model_primary_spec）
  text = await adapter_router.chat(messages)

  # 指定 spec
  text = await adapter_router.chat(messages, model_spec="ollama://gemma3:4b")

  # 直接获取 Adapter 实例
  adapter = adapter_router.get("mlx://mlx-community/Qwen3-30B-A3B-4bit")
"""
from __future__ import annotations

import logging
from typing import Any

from rhythmind.adapters.model_adapter import ModelAdapter

logger = logging.getLogger(__name__)


class AdapterRouter:
    """
    Model Adapter 路由器。

    线程安全：_instances 仅在单线程（主 event loop）中写入，
    且每次写入前 key 已确定，不会产生竞争。
    """

    def __init__(self) -> None:
        self._instances: dict[str, ModelAdapter] = {}

    # ── 获取 / 创建 Adapter ───────────────────────────────────────────────

    def get(self, model_spec: str) -> ModelAdapter:
        """
        根据 model_spec 返回对应的 Adapter 实例（缓存）。

        对于 MLXAdapter，首次调用 get() 只创建 Adapter 对象，
        模型文件在第一次 chat() 调用时才加载（懒加载）。
        """
        if model_spec not in self._instances:
            self._instances[model_spec] = self._create(model_spec)
            logger.debug("adapter_router.created spec=%s", model_spec)
        return self._instances[model_spec]

    def _create(self, model_spec: str) -> ModelAdapter:
        """工厂方法：根据前缀选择适配器实现。"""
        if model_spec.startswith("mlx://"):
            from rhythmind.adapters.mlx_adapter import MLXAdapter
            model_path = model_spec[len("mlx://"):]
            return MLXAdapter(model_path)

        if model_spec.startswith("ollama://"):
            from rhythmind.adapters.ollama_adapter import OllamaAdapter
            model_name = model_spec[len("ollama://"):]
            return OllamaAdapter(model_name)

        # 其余全部走 LiteLLM（处理 openai/, anthropic/, 及别名如 "primary"）
        from rhythmind.adapters.litellm_adapter import LiteLLMAdapter
        return LiteLLMAdapter(model_spec)

    # ── 快捷调用接口 ──────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model_spec: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """
        通过路由层调用 LLM。

        Args:
            messages:        OpenAI 格式 messages 列表
            model_spec:      None → 使用 settings.model_primary_spec
                             空字符串 → 回退到 settings.model_primary（LiteLLM 别名）
            temperature:     采样温度
            max_tokens:      最大 token 数
            response_format: {"type": "json_object"} 等
        """
        spec = model_spec
        if spec is None:
            from rhythmind.config import settings
            spec = settings.model_primary_spec or settings.model_primary

        adapter = self.get(spec)
        adapter_kind = spec.split("://", 1)[0] if "://" in spec else "litellm"

        # Prometheus 埋点（无 prometheus_client 时为 no-op）
        from rhythmind.observability import LLM_CALLS, LLM_LATENCY
        with LLM_LATENCY.labels(adapter_kind).time():
            try:
                result = await adapter.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    **kwargs,
                )
                LLM_CALLS.labels(adapter_kind, "success").inc()
                return result
            except Exception:
                LLM_CALLS.labels(adapter_kind, "error").inc()
                raise

    async def health_check(self, model_spec: str | None = None) -> bool:
        """检查指定适配器的健康状态（默认检查主模型）。"""
        spec = model_spec
        if spec is None:
            from rhythmind.config import settings
            spec = settings.model_primary_spec or settings.model_primary
        return await self.get(spec).health_check()

    def clear_cache(self) -> None:
        """清除 Adapter 实例缓存（测试用）。"""
        self._instances.clear()


# ── 模块级单例（整个进程共享）────────────────────────────────────────────
adapter_router = AdapterRouter()
