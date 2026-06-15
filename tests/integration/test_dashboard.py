"""
tests/integration/test_dashboard.py — Dashboard 路由专项测试

覆盖 6 端点（拆分后 dashboard.py 保留的端点）：
  GET  /qm/api/dashboard               — 仪表盘汇总
  GET  /qm/api/influxdb/timeseries     — InfluxDB 时序查询
  POST /qm/api/analyze                 — 触发 AI 分析
  POST /qm/api/import-facts            — 批量导入事实
  POST /qm/api/upload/file             — 多模态文件上传
  POST /qm/api/chat                    — Chat 代理

注：本文件为拆分后专项测试，完整套件见 test_dashboard_reports.py。
"""
from __future__ import annotations

import os

# 必须在 import rhythmind 之前注入 env
os.environ["ENV"] = "dev"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "integration-test-dash-secret!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-dash-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("MODEL_PRIMARY_SPEC", "ollama://stub")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")

import pytest

# Fixtures: auth_headers / app_client 由 conftest.py 提供
# （tests/integration/conftest.py line 37-67）


# ── Dashboard 端点 ────────────────────────────────────────────────────────


class TestDashboardEndpoint:
    @pytest.mark.asyncio
    async def test_empty(self, app_client, auth_headers):
        """无数据时返回 ok + 空 data。"""
        resp = await app_client.get("/qm/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "data" in body
        assert isinstance(body["data"], dict)

    @pytest.mark.asyncio
    async def test_unauthorized(self, app_client):
        """无 Bearer 时返回 401/403。"""
        resp = await app_client.get("/qm/api/dashboard")
        assert resp.status_code in (401, 403)


class TestInfluxTimeseries:
    @pytest.mark.asyncio
    async def test_metric_whitelist(self, app_client, auth_headers):
        """非白名单 metric 返回 400。"""
        resp = await app_client.get(
            "/qm/api/influxdb/timeseries",
            params={"metric": "hacker_field", "user_id": "test_user_001"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "不支持的 metric" in resp.text

    @pytest.mark.asyncio
    async def test_aggregation_whitelist(self, app_client, auth_headers):
        """非白名单 aggregation 返回 400。"""
        resp = await app_client.get(
            "/qm/api/influxdb/timeseries",
            params={
                "metric": "heart_rate_avg",
                "aggregation": "1y",
                "user_id": "test_user_001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_range_must_be_relative(self, app_client, auth_headers):
        """range 必须以 - 开头（防 Flux 注入）。"""
        resp = await app_client.get(
            "/qm/api/influxdb/timeseries",
            params={
                "metric": "heart_rate_avg",
                "range": "2025-01-01",  # 绝对时间，应拒绝
                "user_id": "test_user_001",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "range 格式错误" in resp.text
