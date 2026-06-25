"""
observability/llm_observe.py — LLM 观测装饰器 (双通道)

提供 @observe_llm 装饰器，自动采集 LLM 调用的 input/output/tokens/cost/latency。

通道 1 (主): Langfuse
  - settings.langfuse_enabled=True 时启用
  - 写入 Langfuse v2 PG 的 observations 表

通道 2 (兜底): 本地表 llm_call_log
  - 始终启用(无论 Langfuse 是否配置)
  - 写入项目自有表,保证 /llm-observe/* 端点总能看到数据
  - /llm-observe/* 路由优先查 Langfuse,失败时 fallback 到本地表

用法:
    @observe_llm(model="gemma-4-12B-it-4bit", agent="adapter_router")
    async def chat(messages, ...) -> str: ...
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
        log.info("llm_observe.disabled langfuse_enabled=False (using local llm_call_log only)")
        return False

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        log.warning("llm_observe.missing_keys (using local llm_call_log only)")
        return False

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log.info(
            "llm_observe.initialized host=%s (dual-write to local + Langfuse)",
            settings.langfuse_host,
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
    """装饰器：自动采集 LLM 调用到 Langfuse + 本地 llm_call_log 表。

    自动记录:
      - input/output
      - model, temperature, max_tokens
      - usage_details (input/output tokens)
      - cost_details
      - latency_ms
      - 成功/失败状态

    双通道:始终写本地表(轻量,100% 可用),Langfuse 可用时再额外上报。
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            t0 = time.perf_counter()
            start_time = time.time()  # wall-clock for DB

            # 解析真实模型名:model="auto" 时从 kwargs['model_spec'] 取
            actual_model = model
            if model == "auto":
                spec = kwargs.get("model_spec")
                if spec:
                    actual_model = spec
                else:
                    try:
                        from rhythmind.config import settings
                        actual_model = settings.model_primary_spec
                    except Exception:
                        actual_model = "unknown"

            # ── Langfuse 上报(可选)───────────────────────────────
            client = get_langfuse()
            trace = None
            generation = None
            if client is not None:
                try:
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
                except Exception as e:
                    log.warning("llm_observe.langfuse_trace_failed: %s", e)
                    trace = None
                    generation = None

            # ── 主调用 ────────────────────────────────────────────
            try:
                result = await func(*args, **kwargs)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                total_tokens = _estimate_tokens(kwargs, result)
                cost = _estimate_cost(model, kwargs, result)

                # 1) 写本地表
                await _write_local_log(
                    agent=agent,
                    model=actual_model,
                    start_time=start_time,
                    latency_ms=latency_ms,
                    total_tokens=total_tokens,
                    total_cost=cost,
                    level="DEFAULT",
                    success=True,
                    error_msg=None,
                )

                # 2) Langfuse end
                if generation is not None:
                    try:
                        generation.end(
                            output=result,
                            usage_details={"total": total_tokens},
                            cost_details={"total": cost},
                            latency_ms=latency_ms,
                        )
                        if trace is not None:
                            trace.update(output={"status": "success", "latency_ms": latency_ms})
                        client.flush()
                    except Exception as e:
                        log.warning("llm_observe.langfuse_end_failed: %s", e)

                return result

            except Exception as e:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                err_msg = f"{type(e).__name__}: {str(e)[:200]}"

                # 1) 写本地表(失败也记)
                await _write_local_log(
                    agent=agent,
                    model=actual_model,
                    start_time=start_time,
                    latency_ms=latency_ms,
                    total_tokens=0,
                    total_cost=0.0,
                    level="ERROR",
                    success=False,
                    error_msg=err_msg,
                )

                # 2) Langfuse error end
                if generation is not None:
                    try:
                        generation.end(
                            output=err_msg,
                            level="ERROR",
                            latency_ms=latency_ms,
                        )
                        if trace is not None:
                            trace.update(
                                output={
                                    "status": "error",
                                    "error": err_msg,
                                    "latency_ms": latency_ms,
                                },
                            )
                        client.flush()
                    except Exception as le:
                        log.warning("llm_observe.langfuse_err_end_failed: %s", le)

                raise

        return async_wrapper

    return decorator


async def _write_local_log(
    *,
    agent: str,
    model: str,
    start_time: float,
    latency_ms: int,
    total_tokens: int,
    total_cost: float,
    level: str,
    success: bool,
    error_msg: str | None,
) -> None:
    """把一次 LLM 调用写到本地 llm_call_log 表。

    失败时只记 warning,不抛出(避免影响主调用流程)。
    """
    try:
        from datetime import UTC, datetime

        from sqlalchemy import text

        from rhythmind.core.memory.manager import AsyncSessionLocal

        start_dt = datetime.fromtimestamp(start_time, tz=UTC)
        end_dt = datetime.fromtimestamp(start_time + latency_ms / 1000.0, tz=UTC)

        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_call_log (
                        agent, model, start_time, end_time, latency_ms,
                        total_tokens, total_cost, level, success, error_msg
                    ) VALUES (
                        :agent, :model, :start_time, :end_time, :latency_ms,
                        :total_tokens, :total_cost, :level, :success, :error_msg
                    )
                    """
                ),
                {
                    "agent": agent,
                    "model": model,
                    "start_time": start_dt,
                    "end_time": end_dt,
                    "latency_ms": latency_ms,
                    "total_tokens": total_tokens,
                    "total_cost": total_cost,
                    "level": level,
                    "success": success,
                    "error_msg": error_msg,
                },
            )
            await session.commit()
    except Exception as e:
        # 写本地表失败不阻断主流程
        log.warning("llm_observe.local_log_write_failed: %s", e)


def _estimate_tokens(kwargs: dict[str, Any], result: str | None) -> int:
    """粗估 token 数(中文 ~1.5 char/token,英文 ~4 char/token)。"""
    messages = kwargs.get("messages", [])
    input_chars = sum(
        len(m.get("content", "")) if isinstance(m, dict) else len(str(m))
        for m in messages
    )
    output_chars = len(result) if result else 0
    return int((input_chars + output_chars) / 2.5)


def _estimate_cost(
    model: str, kwargs: dict[str, Any], result: str | None
) -> float:
    """基于模型估算成本(USD)。"""
    total_tokens = _estimate_tokens(kwargs, result)
    cost_per_1k = {
        "gpt-4o": 0.005,
        "gpt-4o-mini": 0.00015,
        "claude-3.5-sonnet": 0.003,
        "claude-sonnet-4-6": 0.003,
        "gemma-4-e4b-it": 0.0,
        "gemma-4-12B-it-4bit": 0.0,  # 本地推理免费
        "qwen3-14b": 0.0,
        "qwen3-30b": 0.0,
    }
    # 模型名归一化
    norm = model.lower().replace("omlX://", "")
    rate = next(
        (v for k, v in cost_per_1k.items() if k in norm),
        0.001,  # 未知模型按 0.001/1k 估算
    )
    return round(total_tokens * rate / 1000, 6)
