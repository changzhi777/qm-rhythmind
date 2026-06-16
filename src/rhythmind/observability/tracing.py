# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
observability/tracing.py — OpenTelemetry 追踪集成

行为:
  - 仅当 OTEL_EXPORTER_OTLP_ENDPOINT 环境变量已设置时才启用 OTLP exporter；
    否则只装 FastAPI instrumentation（产生 span 但不出网，方便单元测试）。
  - opentelemetry-* 是可选依赖：未安装时 install_tracing 退化为 no-op。

业务侧手工 span:
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("hermes.recall_memory") as span:
        span.set_attribute("user_id", user_id)
        ...
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def install_tracing(app: FastAPI, service_name: str = "rhythmind-api") -> None:
    """在 FastAPI app 上启用 OpenTelemetry FastAPI instrumentation。

    若 opentelemetry-sdk 未安装 → 静默 no-op。
    若 OTEL_EXPORTER_OTLP_ENDPOINT 未设置 → 只装 instrumentation，不导出。
    """
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("tracing.opentelemetry_unavailable — tracing disabled")
        return

    resource = Resource.create({
        "service.name": service_name,
        "service.namespace": "rhythmind",
        "deployment.environment": os.getenv("ENV", "dev"),
    })
    provider = TracerProvider(resource=resource)

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
            logger.info("tracing.otlp_exporter_enabled endpoint=%s", otlp_endpoint)
        except ImportError:
            logger.warning(
                "tracing.otlp_exporter_unavailable — install opentelemetry-exporter-otlp-proto-http"  # noqa: E501
            )

    trace.set_tracer_provider(provider)

    # FastAPI instrumentation
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        logger.info("tracing.fastapi_instrumented service=%s", service_name)
    except ImportError:
        logger.warning(
            "tracing.fastapi_instrumentor_unavailable — install opentelemetry-instrumentation-fastapi"  # noqa: E501
        )
