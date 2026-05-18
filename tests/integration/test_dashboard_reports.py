# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Dashboard & Report E2E Tests
# ─────────────────────────────────────────────────────────────────────────────
"""
Dashboard + Report API 端点测试：
  - /reports         — AI 分析报告列表
  - /reports/{id}    — 单篇报告详情
  - /reports/{id}/download — PDF 下载
  - /dashboard       — 仪表盘汇总数据
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

# 必须在 import rhythmind 之前注入 env
os.environ["ENV"] = "dev"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "integration-test-secret-32-chars-min!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-integration-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("MODEL_PRIMARY_SPEC", "ollama://stub")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")


import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test_user_001"}


@pytest.fixture
async def app_client(patched_redis):
    """返回一个绑定到 FastAPI app 的 AsyncClient。"""
    from rhythmind.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def patched_redis(monkeypatch):
    """把 rate_limit + LoopGuard 的 redis.from_url 换成 fakeredis。"""
    import fakeredis.aioredis as fake_aioredis

    fake = fake_aioredis.FakeRedis(decode_responses=True)

    def _from_url(*args, **kwargs):
        return fake

    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", _from_url, raising=True)

    import rhythmind.api.rate_limit as rl
    rl._redis_client = None  # type: ignore[attr-defined]

    yield fake

    await fake.flushdb()
    await fake.aclose()


@pytest.fixture
async def report_with_data(patched_redis):
    """创建测试报告数据。"""
    from rhythmind.core.memory.fact_manager import FactManager

    fm = FactManager("test_user_001")
    await fm.write_fact(
        "ai_report",
        "analysis",
        {
            "content": """# 健康分析报告

## 总体评价
您的整体健康状况良好，运动能力较强。

## 运动能力评估
- VO2Max: 45 ml/kg/min（优秀）
- 耐力水平：良好

## 健康建议
1. 保持每周3次有氧运动
2. 注意休息和睡眠质量
""",
            "model": "gemma-4b",
            "timestamp": datetime.now(tz=UTC).isoformat(),
        },
        source="test",
    )

    history = await fm.query_history("ai_report", "analysis", limit=10)
    return history[0].id if history else None


# ── 测试用例 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reports_list_empty(app_client, auth_headers):
    """报告列表为空时返回空数组。"""
    resp = await app_client.get("/qm/api/reports", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "reports" in data
    assert isinstance(data["reports"], list)


@pytest.mark.asyncio
async def test_reports_list_with_data(app_client, auth_headers, report_with_data):
    """报告列表有数据时返回报告数组。"""
    resp = await app_client.get("/qm/api/reports", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["reports"]) == 1
    assert "content" in data["reports"][0] or "preview" in data["reports"][0]


@pytest.mark.asyncio
async def test_report_detail_not_found(app_client, auth_headers):
    """报告不存在时返回 404。"""
    resp = await app_client.get("/qm/api/reports/99999", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "报告不存在"


@pytest.mark.asyncio
async def test_report_detail_success(app_client, auth_headers, report_with_data):
    """报告详情成功返回。"""
    resp = await app_client.get(f"/qm/api/reports/{report_with_data}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "report" in data
    assert "content" in data["report"]
    assert "model" in data["report"]
    assert "timestamp" in data["report"]


@pytest.mark.asyncio
async def test_report_download_not_found(app_client, auth_headers):
    """下载不存在的报告返回 404。"""
    resp = await app_client.get("/qm/api/reports/99999/download", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "报告不存在"


@pytest.mark.asyncio
async def test_report_download_success_pdf_format(app_client, auth_headers, report_with_data):
    """下载报告成功返回 PDF 格式。"""
    resp = await app_client.get(f"/qm/api/reports/{report_with_data}/download", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert ".pdf" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_report_download_filename_format(app_client, auth_headers, report_with_data):
    """下载文件名格式为：用户ID_年月日时分秒.pdf"""
    resp = await app_client.get(f"/qm/api/reports/{report_with_data}/download", headers=auth_headers)
    assert resp.status_code == 200
    content_disp = resp.headers["content-disposition"]
    # 文件名格式：test_user_001_20260515xxxxxx.pdf
    assert "test_user_001_" in content_disp
    assert ".pdf" in content_disp


@pytest.mark.asyncio
async def test_dashboard_empty(app_client, auth_headers):
    """仪表盘无数据时返回空 data。"""
    resp = await app_client.get("/qm/api/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "data" in data
    assert isinstance(data["data"], dict)


@pytest.mark.asyncio
async def test_unauthorized_access(app_client):
    """无认证时返回 401。"""
    resp = await app_client.get("/qm/api/reports")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_ping_endpoint(app_client):
    """健康检查端点正常。"""
    resp = await app_client.get("/ping")
    assert resp.status_code == 200
    assert "status" in resp.json()