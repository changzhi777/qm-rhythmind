"""
observability/llm_observe.py — Langfuse LLM 观测装饰器

提供 @observe_llm 装饰器，自动采集 LLM 调用的 input/output/tokens/cost/latency。
Langfuse 禁用时退化为 no-op，零开销。

用法：
    @observe_llm(model="gpt-4o", agent="coach_agent")
    async def generate(self, messages, ...) -> str:
        ...
"""
from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_langfuse_client: Any = None


def init_langfuse() -> bool:
    """初始化 Langfuse 客户端。返回是否成功启用。"""
    global _langfuse_client
    from rhythmind.config import settings

    if not settings.langfuse_enabled:
        log.info("llm_observe.disabled langfuse_enabled=False")
        return False

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.warning("llm_observe.missing_keys")
        return False

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log.info(
            "llm_observe.initialized host=%s", settings.langfuse_host,
        )
        return True
    except Exception as e:
        log.error("llm_observe.init_failed error=%s", e)
        _langfuse_client = None
        return False


def get_langfuse() -> Any:  # noqa: ANN401
    """获取 Langfuse 客户端单例。"""
    return _langfuse_client


def observe_llm(
    model: str = "unknown",
    agent: str = "unknown",
) -> Callable[..., Any]:
    """装饰器：自动采集 LLM 调用到 Langfuse。

    自动记录：
      - input/output
      - model, temperature, max_tokens
      - usage_details（input/output tokens）
      - cost_details
      - latency_ms

    Langfuse 禁用时直接透传，无开销。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            client = get_langfuse()
            if client is None:
                return await func(*args, **kwargs)

            t0 = time.perf_counter()
            trace = client.trace(
                name=f"{agent}.{func.__name__}",
                metadata={"agent": agent, "function": func.__name__},
            )
            generation = trace.generation(
                name=f"{func.__name__}",
                model=model,
                input=kwargs.get("messages", str(args[1:])),
                model_parameters={
                    "temperature": kwargs.get("temperature", 0.3),
                    "max_tokens": kwargs.get("max_tokens", 1024),
                },
            )

            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000

                generation.end(
                    output=result,
                    usage_details={"total": _estimate_tokens(kwargs, result)},
                    cost_details=_estimate_cost(model, kwargs, result),
                    latency_ms=latency_ms,
                )
                trace.update(output={"status": "success", "latency_ms": latency_ms})

                client.flush()
                return result
            except Exception as e:
                latency_ms = (time.perf_counter() - t0) * 1000
                generation.end(
                    output=str(e),
                    level="ERROR",
                    latency_ms=latency_ms,
                )
                trace.update(
                    output={
                        "status": "error",
                        "error": str(e),
                        "latency_ms": latency_ms,
                    },
                )
                client.flush()
                raise

        return async_wrapper

    return decorator


def _estimate_tokens(kwargs: dict[str, Any], result: str | None) -> int:
    """粗估 token 数（中文 ~1.5 char/token，英文 ~4 char/token）。"""
    messages = kwargs.get("messages", [])
    input_chars = sum(
        len(m.get("content", "")) if isinstance(m, dict) else len(str(m))
        for m in messages
    )
    output_chars = len(result) if result else 0
    return int((input_chars + output_chars) / 2.5)


def _estimate_cost(
    model: str, kwargs: dict[str, Any], result: str | None
) -> dict[str, Any]:
    """基于模型估算成本（USD）。"""
    total_tokens = _estimate_tokens(kwargs, result)
    cost_per_1k = {
        "gpt-4o": 0.005,
        "gpt-4o-mini": 0.00015,
        "claude-3.5-sonnet": 0.003,
        "gemma-4-e4b-it": 0.0,
        "qwen3-14b": 0.0,
    }
    rate = cost_per_1k.get(model, 0.001)
    return {"total": round(total_tokens * rate / 1000, 6)}
