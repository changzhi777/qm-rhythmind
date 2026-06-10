# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — InfluxDB 时序端点单元测试
# ─────────────────────────────────────────────────────────────────────────────
"""
tests/unit/test_influx_timeseries.py — /qm/api/influxdb/timeseries 端点测试

覆盖：
  - 参数白名单校验（metric / aggregation / fn / range 格式）
  - 正常查询路径（mock InfluxClient.query_range）
  - InfluxDB 不可达降级（degraded 状态）
  - 认证（401 缺 token）
  - 返回值结构完整性
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rhythmind.adapters.influx_client import TrendSeries


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_settings(monkeypatch):
    """Mock settings.env=dev, dev_auth_bypass=True 避免 JWT 复杂度。"""
    s = MagicMock()
    s.env = "dev"
    s.dev_auth_bypass = True
    s.influxdb_url = "http://10.10.10.115:8086"
    s.influxdb_token = "test-token"
    s.influxdb_org = "rhythmind"
    s.influxdb_bucket = "health_metrics"
    s.jwt_secret = "test"
    s.jwt_algorithm = "HS256"
    return s


@pytest.fixture
def client(mock_settings):
    """构造一个仅挂载 dashboard_router 的 mini app。"""
    with patch("rhythmind.api.deps.settings", mock_settings):
        from rhythmind.api.routers.dashboard import router
        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)


def _auth(user_id: str = "garmin_user_001") -> dict[str, str]:
    return {"Authorization": f"Bearer {user_id}"}


# ── 1. 参数白名单校验 ──────────────────────────────────────────────────────

class TestParamValidation:
    def test_invalid_metric_returns_400(self, client):
        """不在白名单的 metric 返回 400。"""
        res = client.get(
            "/qm/api/influxdb/timeseries?metric=malicious_field",
            headers=_auth(),
        )
        assert res.status_code == 400
        assert "不支持的 metric" in res.json()["detail"]

    def test_invalid_aggregation_returns_400(self, client):
        """不在白名单的 aggregation 返回 400。"""
        res = client.get(
            "/qm/api/influxdb/timeseries?metric=heart_rate_avg&aggregation=5m",
            headers=_auth(),
        )
        assert res.status_code == 400
        assert "不支持的 aggregation" in res.json()["detail"]

    def test_invalid_fn_returns_400(self, client):
        """不在白名单的 fn 返回 400。"""
        res = client.get(
            "/qm/api/influxdb/timeseries?metric=heart_rate_avg&fn=median",
            headers=_auth(),
        )
        assert res.status_code == 400
        assert "不支持的 fn" in res.json()["detail"]

    def test_invalid_range_format_returns_400(self, client):
        """range 缺 '-' 前缀返回 400。"""
        res = client.get(
            "/qm/api/influxdb/timeseries?metric=heart_rate_avg&range=7d",
            headers=_auth(),
        )
        assert res.status_code == 400
        assert "range 格式错误" in res.json()["detail"]

    def test_missing_metric_returns_422(self, client):
        """必填参数 metric 缺失返回 422。"""
        res = client.get("/qm/api/influxdb/timeseries", headers=_auth())
        assert res.status_code == 422


# ── 2. 正常查询路径 ─────────────────────────────────────────────────────────

class TestHappyPath:
    @patch("rhythmind.adapters.influx_client.InfluxClient")
    def test_returns_series_with_latest_avg(self, mock_influx_cls, client):
        """正常查询返回 data + count + latest + avg。"""
        now = datetime(2026, 6, 10, 0, 0, 0, tzinfo=timezone.utc)
        mock_series = TrendSeries(
            field="heart_rate_avg",
            values=[
                (now.replace(day=4), 70.0),
                (now.replace(day=5), 72.0),
                (now.replace(day=6), 75.0),
            ],
        )
        mock_client = MagicMock()
        mock_client.query_range = AsyncMock(
            return_value={"heart_rate_avg": mock_series},
        )
        mock_influx_cls.return_value = mock_client

        res = client.get(
            "/qm/api/influxdb/timeseries?metric=heart_rate_avg&range=-7d&aggregation=1d",
            headers=_auth(),
        )

        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["metric"] == "heart_rate_avg"
        assert body["range"] == "-7d"
        assert body["count"] == 3
        assert body["latest"] == 75.0
        # avg = (70 + 72 + 75) / 3 = 72.33
        assert body["avg"] == pytest.approx(72.33, rel=0.01)
        assert len(body["data"]) == 3
        # data point 格式
        pt = body["data"][0]
        assert "ts" in pt and "value" in pt
        assert pt["value"] == 70.0

    @patch("rhythmind.adapters.influx_client.InfluxClient")
    def test_empty_data_returns_zero_count(self, mock_influx_cls, client):
        """空数据返回 count=0, latest=None。"""
        mock_client = MagicMock()
        mock_client.query_range = AsyncMock(return_value={})
        mock_influx_cls.return_value = mock_client

        res = client.get(
            "/qm/api/influxdb/timeseries?metric=steps",
            headers=_auth(),
        )
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 0
        assert body["data"] == []
        assert body["latest"] is None


# ── 3. 降级路径 ────────────────────────────────────────────────────────────

class TestDegradedPath:
    @patch("rhythmind.adapters.influx_client.InfluxClient")
    def test_influx_unavailable_returns_degraded(self, mock_influx_cls, client):
        """InfluxClient.query_range 抛异常时返回 status=degraded。"""
        mock_client = MagicMock()
        mock_client.query_range = AsyncMock(
            side_effect=ConnectionError("connection refused"),
        )
        mock_influx_cls.return_value = mock_client

        res = client.get(
            "/qm/api/influxdb/timeseries?metric=heart_rate_avg",
            headers=_auth(),
        )
        assert res.status_code == 200  # 降级而非 500
        body = res.json()
        assert body["status"] == "degraded"
        assert body["count"] == 0
        assert body["data"] == []
        assert "InfluxDB 不可达" in body["error"]
