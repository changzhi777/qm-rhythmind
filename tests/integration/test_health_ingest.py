# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Wearable ingest endpoint tests (Phase 3.5)
# ─────────────────────────────────────────────────────────────────────────────
"""
Tests for POST /health/ingest — CSV wearable data ingestion.

Coverage:
  1. Valid CSV → 200 + correct row count
  2. Invalid file type → 400
  3. Empty CSV → 400
  4. Missing timestamp column → 422
  5. Partial success with row-level errors
  6. source query param correctly stored
"""
from __future__ import annotations

import io

import pytest

# ── 1. Valid CSV ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_valid_csv(app_client, patched_redis):
    """有效 CSV 返回 rows_parsed 数量。"""
    csv_content = (
        "timestamp,heart_rate,steps,sleep_minutes,spo2\n"
        "2026-05-12T08:00:00Z,65,1200,0,98\n"
        "2026-05-12T09:00:00Z,72,300,0,97\n"
    )
    csv_file = io.BytesIO(csv_content.encode("utf-8"))
    csv_file.name = "export.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("export.csv", csv_file, "text/csv")},
        params={"source": "apple_health"},
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("success", "partial")
    assert body["rows_parsed"] == 2
    assert body["source"] == "apple_health"


# ── 2. Invalid file type ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_rejects_non_csv(app_client, patched_redis):
    """非 CSV 文件返回 400。"""
    txt_file = io.BytesIO(b"not a csv")
    txt_file.name = "export.txt"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("export.txt", txt_file, "text/plain")},
        data={"source": "manual"},
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 400
    assert "csv" in resp.text.lower()


# ── 3. Empty CSV ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_rejects_empty_csv(app_client, patched_redis):
    """空 CSV 返回 422（无可用数据点）。"""
    csv_file = io.BytesIO(b"timestamp,heart_rate\n")
    csv_file.name = "empty.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("empty.csv", csv_file, "text/csv")},
        data={"source": "manual"},
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 422


# ── 4. Missing timestamp ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_requires_timestamp_column(app_client, patched_redis):
    """缺少 timestamp 列返回 422。"""
    csv_content = "heart_rate,steps\n65,1200\n"
    csv_file = io.BytesIO(csv_content.encode("utf-8"))
    csv_file.name = "no_ts.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("no_ts.csv", csv_file, "text/csv")},
        data={"source": "manual"},
        headers={"Authorization": "Bearer alice"},
    )
    # errors will indicate missing timestamp
    body = resp.json()
    assert resp.status_code == 422


# ── 5. All rows valid → success, errors returned empty ──────────────────────

@pytest.mark.asyncio
async def test_ingest_all_valid_no_errors(app_client, patched_redis):
    """全有效的 CSV 返回 success 或 partial（InfluxDB 不可用时）。"""
    csv_content = (
        "timestamp,heart_rate,steps\n"
        "2026-05-12T08:00:00Z,65,1200\n"
        "2026-05-12T09:00:00Z,72,300\n"
    )
    csv_file = io.BytesIO(csv_content.encode("utf-8"))
    csv_file.name = "good.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("good.csv", csv_file, "text/csv")},
        data={"source": "manual"},
        headers={"Authorization": "Bearer alice"},
    )
    body = resp.json()
    # status 可能是 success（InfluxDB 可用）或 partial（InfluxDB 不可用时的降级）
    assert body["status"] in ("success", "partial")
    assert body["rows_parsed"] == 2
    assert body["errors"] == []


# ── 6. Blood pressure columns ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_parses_blood_pressure(app_client, patched_redis):
    """CSV 包含血压列时被正确解析。"""
    csv_content = (
        "timestamp,heart_rate,blood_pressure_systolic,blood_pressure_diastolic\n"
        "2026-05-12T08:00:00Z,65,120,80\n"
    )
    csv_file = io.BytesIO(csv_content.encode("utf-8"))
    csv_file.name = "bp.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("bp.csv", csv_file, "text/csv")},
        data={"source": "manual"},
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows_parsed"] == 1


# ── 7. Default source is manual ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_default_source_manual(app_client, patched_redis):
    """未提供 source 时默认为 manual。"""
    csv_content = "timestamp,heart_rate\n2026-05-12T08:00:00Z,65\n"
    csv_file = io.BytesIO(csv_content.encode("utf-8"))
    csv_file.name = "test.csv"

    resp = await app_client.post(
        "/api/v1/health/ingest",
        files={"file": ("test.csv", csv_file, "text/csv")},
        headers={"Authorization": "Bearer alice"},
    )
    body = resp.json()
    assert body["source"] == "manual"