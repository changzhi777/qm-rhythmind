# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_tracing.py — install_tracing() 单元测试

覆盖 line 45-47 (ImportError 退化为 no-op) + line 66-67 (OTLP exporter 缺失)
+ line 78-79 (FastAPI instrumentation 缺失) 共 4 行 missing。

策略：使用 importlib + sys.modules 注入，模拟 opentelemetry 各子包 ImportError。
"""
from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI


def _block_opentelemetry_submodules(submodules: list[str]) -> None:
    """将 opentelemetry.* 子模块设为 None → 触发 ImportError。"""
    for name in submodules:
        sys.modules[name] = None  # type: ignore[assignment]
    yield  # 让 fixture 完成后清理
    for name in submodules:
        sys.modules.pop(name, None)


class TestInstallTracingFallbacks:
    """覆盖 opentelemetry 各种 ImportError 路径。

    技巧：sys.modules[name] = None 显式触发 ImportError（MagicMock 会让导入成功）。
    """

    def test_import_error_returns_silently_when_opentelemetry_sdk_unavailable(self, caplog):
        """opentelemetry-sdk 未安装时 install_tracing 静默 return（line 45-47）。"""
        from rhythmind.observability import tracing

        blocked = ["opentelemetry", "opentelemetry.sdk", "opentelemetry.sdk.trace"]
        for name in blocked:
            sys.modules[name] = None  # type: ignore[assignment]
        try:
            with caplog.at_level("WARNING"):
                # 不应抛异常
                tracing.install_tracing(app=MagicMock(), service_name="test")
            # 验证日志含 disabled 提示
            assert any("tracing disabled" in r.message.lower() for r in caplog.records)
        finally:
            for name in blocked:
                sys.modules.pop(name, None)

    def test_otlp_exporter_import_error_continues(self, monkeypatch, caplog):
        """OTEL endpoint 设置但 exporter 包未安装时（line 66-67）：logger.warning + 继续。"""
        from rhythmind.observability import tracing

        # 设置 endpoint（应触发 OTLPSpanExporter 导入路径）
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318")

        # mock opentelemetry 主要子包 + 阻止 exporter
        mock_ok = {
            "opentelemetry": MagicMock(),
            "opentelemetry.sdk": MagicMock(),
            "opentelemetry.sdk.trace": MagicMock(),
            "opentelemetry.sdk.resources": MagicMock(),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }
        blocked = [
            "opentelemetry.exporter.otlp",
            "opentelemetry.exporter.otlp.proto",
            "opentelemetry.exporter.otlp.proto.http",
            "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        ]
        for name, mod in mock_ok.items():
            sys.modules[name] = mod
        for name in blocked:
            sys.modules[name] = None  # type: ignore[assignment]
        try:
            with caplog.at_level("WARNING"):
                tracing.install_tracing(app=MagicMock(), service_name="test")
            # 验证日志含 exporter 不可用提示
            assert any("otlp_exporter" in r.message.lower() for r in caplog.records)
        finally:
            for name in list(mock_ok) + blocked:
                sys.modules.pop(name, None)

    def test_fastapi_instrumentor_import_error_continues(self, monkeypatch, caplog):
        """FastAPIInstrumentor 未安装时（line 78-79）：logger.warning + 继续。"""
        from rhythmind.observability import tracing

        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        mock_ok = {
            "opentelemetry": MagicMock(),
            "opentelemetry.sdk": MagicMock(),
            "opentelemetry.sdk.trace": MagicMock(),
            "opentelemetry.sdk.resources": MagicMock(),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }
        blocked = [
            "opentelemetry.instrumentation",
            "opentelemetry.instrumentation.fastapi",
        ]
        for name, mod in mock_ok.items():
            sys.modules[name] = mod
        for name in blocked:
            sys.modules[name] = None  # type: ignore[assignment]
        try:
            with caplog.at_level("WARNING"):
                tracing.install_tracing(app=MagicMock(), service_name="test")
            # 验证日志含 fastapi_instrumentor 不可用提示
            assert any("fastapi_instrumentor" in r.message.lower() for r in caplog.records)
        finally:
            for name in list(mock_ok) + blocked:
                sys.modules.pop(name, None)
