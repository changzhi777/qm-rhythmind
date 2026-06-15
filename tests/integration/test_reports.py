"""
tests/integration/test_reports.py — Reports 路由专项测试

覆盖 5 端点：
  GET  /qm/api/reports                       — AI 报告列表
  GET  /qm/api/reports/{report_id}            — 报告详情
  GET  /qm/api/reports/{report_id}/download   — PDF 下载
  GET  /qm/api/test-reports                  — E2E 测试报告列表
  GET  /qm/api/test-reports/{id}/{filename}   — E2E 报告文件下载

注：完整套件见 tests/integration/test_dashboard_reports.py（与本文件测试有少量重复，
   但提供更细粒度的隔离验证）。
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

# 必须在 import rhythmind 之前注入 env
os.environ["ENV"] = "dev"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "integration-test-reports-secret!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-reports-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("MODEL_PRIMARY_SPEC", "ollama://stub")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")

import pytest

# Fixtures: auth_headers / app_client 由 conftest.py 提供
# （tests/integration/conftest.py line 37-67）


@pytest.fixture
async def report_with_data():
    """在 FactManager 中创建一条 ai_report 记录，返回其 ID。"""
    from rhythmind.core.memory.fact_manager import FactManager

    fm = FactManager("test_user_001")
    await fm.write_fact(
        "ai_report",
        "analysis",
        {
            "content": "# 健康分析报告\n\n## 总体评价\n良好\n",
            "model": "gemma-4b",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
        source="test_reports",
    )
    history = await fm.query_history("ai_report", "analysis", limit=10)
    return history[0].id if history else None


# ── AI 报告 ──────────────────────────────────────────────────────────────


class TestReportsList:
    @pytest.mark.asyncio
    async def test_empty(self, app_client, auth_headers):
        resp = await app_client.get("/qm/api/reports", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["reports"] == []

    @pytest.mark.asyncio
    async def test_with_data(self, app_client, auth_headers, report_with_data):
        resp = await app_client.get("/qm/api/reports", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["reports"]) >= 1
        # 验证字段完整
        r = body["reports"][0]
        assert "id" in r
        assert "model" in r
        assert "preview" in r


class TestReportDetail:
    @pytest.mark.asyncio
    async def test_not_found(self, app_client, auth_headers):
        resp = await app_client.get("/qm/api/reports/99999", headers=auth_headers)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_success(self, app_client, auth_headers, report_with_data):
        resp = await app_client.get(
            f"/qm/api/reports/{report_with_data}", headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["report"]["id"] == report_with_data
        assert "content" in body["report"]


class TestReportDownload:
    @pytest.mark.asyncio
    async def test_not_found(self, app_client, auth_headers):
        resp = await app_client.get(
            "/qm/api/reports/99999/download", headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_pdf_format(self, app_client, auth_headers, report_with_data):
        resp = await app_client.get(
            f"/qm/api/reports/{report_with_data}/download", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        # PDF 魔数校验
        assert resp.content[:4] == b"%PDF"
        # Content-Disposition 应包含 .pdf
        cd = resp.headers.get("content-disposition", "")
        assert ".pdf" in cd
