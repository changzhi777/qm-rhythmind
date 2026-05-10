# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
observability — Prometheus metrics + OpenTelemetry traces

公开 API（仅这些是稳定的，其他符号视为实现细节）：
  - install_metrics(app)          : 注册 /metrics 端点 + 中间件
  - install_tracing(app)          : OTel FastAPI instrumentation
  - HTTP_REQUESTS / HTTP_LATENCY  : Counter / Histogram，可在业务代码内 .inc/.observe
  - LLM_CALLS / LLM_LATENCY       : Counter / Histogram
  - COMPLIANCE_BLOCKS             : Counter
  - record_pool_hit / record_pool_miss
"""
from rhythmind.observability.metrics import (  # noqa: F401
    COMPLIANCE_BLOCKS,
    HTTP_LATENCY,
    HTTP_REQUESTS,
    LLM_CALLS,
    LLM_LATENCY,
    install_metrics,
    record_pool_hit,
    record_pool_miss,
)
from rhythmind.observability.tracing import install_tracing  # noqa: F401
