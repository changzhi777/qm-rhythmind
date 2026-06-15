"""
tests/unit/test_observability.py — Observability 单元测试

策略：
  - prometheus_client 可用时用 TestClient 验证中间件计数
  - 不可用时验证 NoopMetric 降级行为
  - Mock OTel 依赖测试 install_tracing 分支
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.testclient import TestClient

from rhythmind.observability.metrics import (
    _PROMETHEUS_AVAILABLE,
    _NoopMetric,
    _resolve_route_template,
    install_metrics,
)

# ── _NoopMetric ─────────────────────────────────────────────────────────────

class TestNoopMetric:

    def test_inc_returns_none(self):
        assert _NoopMetric().labels("a").inc() is None

    def test_inc_with_amount_no_error(self):
        _NoopMetric().labels("a").inc(5)

    def test_observe_returns_none(self):
        assert _NoopMetric().labels("a").observe(1.5) is None

    def test_time_context_manager(self):
        with _NoopMetric().time():
            pass

    def test_labels_returns_noop(self):
        assert isinstance(_NoopMetric().labels("x", "y"), _NoopMetric)


# ── PrometheusMiddleware ────────────────────────────────────────────────────

class TestPrometheusMiddleware:

    def _make_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/api/v1/ping")
        async def ping():
            return {"ok": True}

        @app.get("/api/v1/fail")
        async def fail():
            raise ValueError("boom")

        install_metrics(app)
        return app

    def test_success_request_returns_200(self):
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200

    def test_error_request_returns_500(self):
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/api/v1/fail")
        assert resp.status_code == 500

    @pytest.mark.skipif(
        not _PROMETHEUS_AVAILABLE, reason="prometheus_client not installed"
    )
    def test_success_increments_http_requests_counter(self):
        from rhythmind.observability.metrics import HTTP_REQUESTS

        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        before = float(HTTP_REQUESTS.labels("GET", "/api/v1/ping", "200")._value.get())
        client.get("/api/v1/ping")
        after = float(HTTP_REQUESTS.labels("GET", "/api/v1/ping", "200")._value.get())
        assert after - before == 1

    @pytest.mark.skipif(
        not _PROMETHEUS_AVAILABLE, reason="prometheus_client not installed"
    )
    def test_error_increments_500_counter(self):
        from rhythmind.observability.metrics import HTTP_REQUESTS

        app = self._make_app()
        client = TestClient(app, raise_server_exceptions=False)

        before = float(HTTP_REQUESTS.labels("GET", "/api/v1/fail", "500")._value.get())
        client.get("/api/v1/fail")
        after = float(HTTP_REQUESTS.labels("GET", "/api/v1/fail", "500")._value.get())
        assert after - before == 1

    def test_noop_path_success_still_works(self):
        """即使 prometheus_client 不可用，请求也正常返回。"""
        client = TestClient(self._make_app(), raise_server_exceptions=False)
        resp = client.get("/api/v1/ping")
        assert resp.json() == {"ok": True}


# ── _resolve_route_template ─────────────────────────────────────────────────

class TestResolveRouteTemplate:

    def test_returns_route_path_when_available(self):
        mock_route = MagicMock()
        mock_route.path = "/api/v1/{item_id}"
        scope = {"type": "http", "route": mock_route, "path": "/api/v1/42"}
        request = Request(scope)
        assert _resolve_route_template(request) == "/api/v1/{item_id}"

    def test_falls_back_to_raw_path(self):
        scope = {"type": "http", "path": "/api/v1/42"}
        request = Request(scope)
        assert _resolve_route_template(request) == "/api/v1/42"

    def test_falls_back_to_unknown(self):
        scope = {"type": "http"}
        request = Request(scope)
        assert _resolve_route_template(request) == "unknown"


# ── install_metrics ─────────────────────────────────────────────────────────

class TestInstallMetrics:

    def test_adds_metrics_route(self):
        app = FastAPI()
        install_metrics(app)
        paths = [r.path for r in app.routes]
        assert "/metrics" in paths

    def test_metrics_endpoint_returns_200(self):
        app = FastAPI()
        install_metrics(app)
        client = TestClient(app)

        resp = client.get("/metrics")
        assert resp.status_code == 200

    @pytest.mark.skipif(
        not _PROMETHEUS_AVAILABLE, reason="prometheus_client not installed"
    )
    def test_metrics_endpoint_contains_metric_names(self):
        app = FastAPI()
        install_metrics(app)
        client = TestClient(app)

        resp = client.get("/metrics")
        assert b"rhythmind_" in resp.content

    def test_metrics_endpoint_without_prometheus(self):
        if _PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client is installed")
        app = FastAPI()
        install_metrics(app)
        client = TestClient(app)

        resp = client.get("/metrics")
        assert b"not installed" in resp.content


# ── LLM / Pool / Compliance 指标 ───────────────────────────────────────────

class TestLLMMetrics:

    def test_llm_calls_increment(self):
        from rhythmind.observability.metrics import LLM_CALLS

        if _PROMETHEUS_AVAILABLE:
            before = float(LLM_CALLS.labels("omlX", "success")._value.get())
            LLM_CALLS.labels("omlX", "success").inc()
            after = float(LLM_CALLS.labels("omlX", "success")._value.get())
            assert after - before == 1
        else:
            LLM_CALLS.labels("omlX", "success").inc()

    def test_llm_latency_observe(self):
        from rhythmind.observability.metrics import LLM_LATENCY

        LLM_LATENCY.labels("omlX").observe(2.5)
        LLM_LATENCY.labels("litellm").observe(0.8)


class TestPoolMetrics:

    def test_pool_hit(self):
        from rhythmind.observability.metrics import POOL_HITS, record_pool_hit

        if _PROMETHEUS_AVAILABLE:
            before = float(POOL_HITS._value.get())
            record_pool_hit()
            assert float(POOL_HITS._value.get()) - before == 1
        else:
            record_pool_hit()

    def test_pool_miss(self):
        from rhythmind.observability.metrics import POOL_MISSES, record_pool_miss

        if _PROMETHEUS_AVAILABLE:
            before = float(POOL_MISSES._value.get())
            record_pool_miss()
            assert float(POOL_MISSES._value.get()) - before == 1
        else:
            record_pool_miss()

    def test_pool_size_gauge(self):
        from rhythmind.observability.metrics import POOL_SIZE

        if _PROMETHEUS_AVAILABLE:
            POOL_SIZE.set(42)
            assert float(POOL_SIZE._value.get()) == 42.0
        else:
            POOL_SIZE.set(42)


class TestComplianceMetrics:

    def test_compliance_blocks_increment(self):
        from rhythmind.observability.metrics import COMPLIANCE_BLOCKS

        if _PROMETHEUS_AVAILABLE:
            before = float(COMPLIANCE_BLOCKS.labels("prompt_audit")._value.get())
            COMPLIANCE_BLOCKS.labels("prompt_audit").inc()
            after = float(
                COMPLIANCE_BLOCKS.labels("prompt_audit")._value.get()
            )
            assert after - before == 1
        else:
            COMPLIANCE_BLOCKS.labels("prompt_audit").inc()


# ── Noop fallback path ──────────────────────────────────────────────────────

class TestNoopFallback:

    def test_generate_latest_without_prometheus(self):
        from rhythmind.observability import metrics as mod
        from rhythmind.observability.metrics import generate_latest

        with patch.object(mod, "_PROMETHEUS_AVAILABLE", False):
            result = generate_latest()
            assert b"not installed" in result


# ── install_tracing ─────────────────────────────────────────────────────────

class TestInstallTracing:

    def test_noop_when_otel_import_fails(self):
        """OTel 未安装时 install_tracing 静默返回。"""
        from rhythmind.observability.tracing import install_tracing

        app = FastAPI()
        # Force ImportError by making opentelemetry unimportable
        import builtins
        real_import = builtins.__import__

        def _block_otel(name, *args, **kwargs):
            if name == "opentelemetry":
                raise ImportError("mock: otel not installed")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", _block_otel):
            install_tracing(app)

    def _inject_otel_mocks(self, mock_provider: MagicMock) -> dict[str, ModuleType]:
        """注入 mock OTel 子模块到 sys.modules，命中局部 import。"""
        mock_trace = MagicMock()
        mock_resource_mod = MagicMock()
        mock_trace_provider_mod = MagicMock()
        mock_trace_provider_mod.TracerProvider = MagicMock(return_value=mock_provider)
        mock_export_mod = MagicMock()
        mock_fastapi_inst_mod = MagicMock()

        mods = {
            "opentelemetry.trace": mock_trace,
            "opentelemetry.sdk": ModuleType("opentelemetry.sdk"),
            "opentelemetry.sdk.resources": mock_resource_mod,
            "opentelemetry.sdk.trace": mock_trace_provider_mod,
            "opentelemetry.sdk.trace.export": mock_export_mod,
            "opentelemetry.instrumentation": ModuleType(
                "opentelemetry.instrumentation"
            ),
            "opentelemetry.instrumentation.fastapi": mock_fastapi_inst_mod,
        }
        return mods, mock_trace, mock_fastapi_inst_mod

    def test_tracing_runs_without_otlp_endpoint(self, monkeypatch):
        """OTel 可用但无 OTLP endpoint → 不添加 exporter。"""
        from rhythmind.observability.tracing import install_tracing

        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        mock_provider = MagicMock()
        mods, _, mock_fastapi_inst_mod = self._inject_otel_mocks(mock_provider)

        with patch.dict(sys.modules, mods):
            app = FastAPI()
            install_tracing(app)

            mock_provider.add_span_processor.assert_not_called()
            mock_fastapi_inst_mod.FastAPIInstrumentor.instrument_app.assert_called_once()

    def test_tracing_with_otlp_endpoint(self, monkeypatch):
        """OTLP endpoint 设置时添加 BatchSpanProcessor。"""
        from rhythmind.observability.tracing import install_tracing

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

        mock_provider = MagicMock()
        mock_bsp = MagicMock()
        mods, _, _ = self._inject_otel_mocks(mock_provider)

        _otel_exp = "opentelemetry.exporter"
        mock_exporter_mod = ModuleType(
            f"{_otel_exp}.otlp.proto.http.trace_exporter"
        )
        mock_exporter_cls = MagicMock()
        mock_exporter_mod.OTLPSpanExporter = mock_exporter_cls
        mods[f"{_otel_exp}"] = ModuleType(_otel_exp)
        mods[f"{_otel_exp}.otlp"] = ModuleType(f"{_otel_exp}.otlp")
        mods[f"{_otel_exp}.otlp.proto"] = ModuleType(
            f"{_otel_exp}.otlp.proto"
        )
        mods[f"{_otel_exp}.otlp.proto.http"] = ModuleType(
            f"{_otel_exp}.otlp.proto.http"
        )
        mods[f"{_otel_exp}.otlp.proto.http.trace_exporter"] = (
            mock_exporter_mod
        )

        mods["opentelemetry.sdk.trace.export"].BatchSpanProcessor = (
            MagicMock(return_value=mock_bsp)
        )

        with patch.dict(sys.modules, mods):
            app = FastAPI()
            install_tracing(app)

            mock_exporter_cls.assert_called_once()
            mock_provider.add_span_processor.assert_called_once_with(mock_bsp)
