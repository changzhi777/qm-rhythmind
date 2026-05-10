# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
observability/metrics.py — Prometheus 指标定义 + /metrics 端点

设计:
  - 全局单例 Registry（默认 prometheus_client.REGISTRY），多 worker 部署需用
    multiprocess mode；详见 DEPLOYMENT.md §3。
  - prometheus_client 是可选依赖：未安装时所有 .inc/.observe 退化为 no-op，
    业务代码无需 try/except。
  - 路由：GET /metrics（无需鉴权，但应通过 NetworkPolicy 限制只允许 Prometheus 抓取）

业务埋点示例:
    from rhythmind.observability import LLM_CALLS, LLM_LATENCY
    with LLM_LATENCY.labels("primary").time():
        ...
    LLM_CALLS.labels("primary", "success").inc()
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ── prometheus_client 可选导入 + no-op 回退 ────────────────────────────────

class _NoopMetric:
    """prometheus_client 未安装时的占位实现，所有调用都是 no-op。"""
    def labels(self, *args: Any, **kwargs: Any) -> "_NoopMetric": return self
    def inc(self, amount: float = 1) -> None: pass
    def observe(self, value: float) -> None: pass
    def set(self, value: float) -> None: pass
    def time(self) -> "_NoopTimer": return _NoopTimer()


class _NoopTimer:
    def __enter__(self) -> "_NoopTimer": return self
    def __exit__(self, *a: Any) -> None: pass


try:
    from prometheus_client import (  # type: ignore[import-not-found]
        CONTENT_TYPE_LATEST,
        REGISTRY,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False
    logger.warning("observability.prometheus_client_unavailable — metrics will be no-op")
    Counter = Histogram = Gauge = lambda *a, **kw: _NoopMetric()  # type: ignore[assignment,misc]
    REGISTRY = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest(*a: Any, **kw: Any) -> bytes:  # type: ignore[no-redef]
        return b"# prometheus_client not installed\n"


# ── 指标定义 ─────────────────────────────────────────────────────────────────

HTTP_REQUESTS = Counter(
    "rhythmind_http_requests_total",
    "HTTP 请求总数",
    ["method", "route", "status"],
)

HTTP_LATENCY = Histogram(
    "rhythmind_http_request_duration_seconds",
    "HTTP 请求处理时长（秒）",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120),
)

LLM_CALLS = Counter(
    "rhythmind_llm_calls_total",
    "LLM 调用总数",
    ["adapter", "result"],   # adapter=mlx|ollama|litellm; result=success|error
)

LLM_LATENCY = Histogram(
    "rhythmind_llm_duration_seconds",
    "LLM 推理时长（秒）",
    ["adapter"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

COMPLIANCE_BLOCKS = Counter(
    "rhythmind_compliance_blocks_total",
    "合规审查拦截次数",
    ["stage"],  # stage=prompt_audit|output_gate
)

POOL_HITS = Counter(
    "rhythmind_agent_pool_hits_total",
    "AgentPool 命中（user 已有缓存 Agent）",
)

POOL_MISSES = Counter(
    "rhythmind_agent_pool_misses_total",
    "AgentPool 未命中（新建 Agent 实例）",
)

POOL_SIZE = Gauge(
    "rhythmind_agent_pool_size",
    "AgentPool 当前驻留 user 数",
)


def record_pool_hit() -> None:
    POOL_HITS.inc()


def record_pool_miss() -> None:
    POOL_MISSES.inc()


# ── HTTP 中间件：自动记录请求计数与时长 ─────────────────────────────────────

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        method = request.method
        # 优先取 route.path 模板（避免 /users/123 / /users/456 各算一行）
        route_path = request.scope.get("path", "unknown")
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed = time.perf_counter() - start
            try:
                # 用模板路径降基数
                route_template = _resolve_route_template(request)
                HTTP_REQUESTS.labels(method, route_template, str(status_code)).inc()
                HTTP_LATENCY.labels(method, route_template).observe(elapsed)
            except Exception:  # pragma: no cover
                pass


def _resolve_route_template(request: Request) -> str:
    """尝试解析为 FastAPI route 模板路径；失败回退 raw path。"""
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return request.scope.get("path", "unknown")


# ── 安装入口 ────────────────────────────────────────────────────────────────

def install_metrics(app: FastAPI) -> None:
    """在 FastAPI app 上挂载 PrometheusMiddleware + GET /metrics 端点。"""
    app.add_middleware(PrometheusMiddleware)

    async def metrics_endpoint() -> Response:
        return Response(
            content=generate_latest(REGISTRY) if _PROMETHEUS_AVAILABLE else generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    app.add_api_route(
        "/metrics",
        metrics_endpoint,
        methods=["GET"],
        include_in_schema=False,
        tags=["infra"],
    )
    logger.info(
        "metrics.installed prometheus_client_available=%s", _PROMETHEUS_AVAILABLE
    )
