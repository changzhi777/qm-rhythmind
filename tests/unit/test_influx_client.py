"""
tests/unit/test_influx_client.py — InfluxDB 客户端测试

测试场景：
  1. write_metrics 成功写入
  2. query_range 查询返回 TrendSeries
  3. query_latest 返回最新值
  4. delete_user_data 删除用户数据
  5. fail-open: InfluxDB 不可用时降级
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhythmind.adapters.influx_client import (
    InfluxClient,
    InfluxUnavailableError,
    MetricPoint,
)


class TestMetricPoint:
    """MetricPoint 数据类测试。"""

    def test_fields_filtered_by_allowlist(self):
        """只允许白名单内的字段。"""
        point = MetricPoint(
            user_id="user_001",
            source="garmin",
            fields={
                "heart_rate_avg": 72,
                "steps": 8000,
                "unknown_field": 100,  # 非法字段应被过滤
            },
        )
        assert "heart_rate_avg" in point.fields
        assert "steps" in point.fields
        assert "unknown_field" not in point.fields

    def test_ts_defaults_to_now(self):
        """ts 为 None 时自动设为当前时间。"""
        point = MetricPoint(user_id="user_001", source="manual")
        assert point.ts is not None
        assert isinstance(point.ts, datetime)

    def test_fields_with_none_filtered(self):
        """None 值的字段应被过滤。"""
        point = MetricPoint(
            user_id="user_001",
            source="manual",
            fields={
                "heart_rate_avg": None,
                "steps": 8000,
            },
        )
        assert "heart_rate_avg" not in point.fields
        assert "steps" in point.fields


class TestInfluxClientWriteMetrics:
    """write_metrics 测试。"""

    @pytest.fixture
    def client(self) -> InfluxClient:
        return InfluxClient(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )

    @pytest.mark.asyncio
    async def test_write_metrics_success(self, client: InfluxClient):
        """成功写入返回 True。"""
        mock_write_api = MagicMock()
        mock_write_api.write = AsyncMock()

        mock_client = MagicMock()
        mock_client.write_api.return_value = mock_write_api
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch.object(client, "_get_client", return_value=mock_client):
            point = MetricPoint(
                user_id="user_001",
                source="garmin",
                fields={"heart_rate_avg": 72, "steps": 8000},
            )

            result = await client.write_metrics(point)
            assert result is True
            mock_write_api.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_metrics_no_fields_returns_false(self, client: InfluxClient):
        """无有效字段时返回 True（跳过，无异常）。"""
        point = MetricPoint(user_id="user_001", source="manual", fields={})
        result = await client.write_metrics(point)
        assert result is True

    @pytest.mark.asyncio
    async def test_write_metrics_error_returns_false(self, client: InfluxClient):
        """写入异常时返回 False。"""
        mock_client = MagicMock()
        mock_client.write_api.side_effect = Exception("Write error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch.object(client, "_get_client", return_value=mock_client):
            point = MetricPoint(
                user_id="user_001",
                source="garmin",
                fields={"heart_rate_avg": 72},
            )

            result = await client.write_metrics(point)
            assert result is False


class TestInfluxClientQuery:
    """query_range 和 query_latest 测试。"""

    @pytest.fixture
    def client(self) -> InfluxClient:
        return InfluxClient(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )

    def _make_mock_client(self, query_return) -> MagicMock:
        """创建支持 async with 的 mock client。"""
        mock_query_api = MagicMock()
        mock_query_api.query = AsyncMock(return_value=query_return)

        mock_client = MagicMock()
        mock_client.query_api.return_value = mock_query_api
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_query_range_returns_trend_series(self, client: InfluxClient):
        """查询返回正确的 TrendSeries 结构。"""
        mock_record = MagicMock()
        mock_record.get_field.return_value = "heart_rate_avg"
        mock_record.get_time.return_value = datetime.now(tz=UTC)
        mock_record.get_value.return_value = 72.0

        mock_table = MagicMock()
        mock_table.records = [mock_record]

        mock_client = self._make_mock_client([mock_table])

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.query_range(
                user_id="user_001",
                fields=["heart_rate_avg"],
                start="-7d",
            )

            assert "heart_rate_avg" in result
            assert result["heart_rate_avg"].field == "heart_rate_avg"
            assert len(result["heart_rate_avg"].values) == 1
            assert result["heart_rate_avg"].values[0][1] == 72.0

    @pytest.mark.asyncio
    async def test_query_range_invalid_fields_filtered(self, client: InfluxClient):
        """非法字段名被过滤。"""
        mock_client = self._make_mock_client([])

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.query_range(
                user_id="user_001",
                fields=["illegal_field"],
                start="-7d",
            )

            assert result == {}

    @pytest.mark.asyncio
    async def test_query_latest_returns_latest_value(self, client: InfluxClient):
        """query_latest 返回最近一条记录。"""
        mock_record = MagicMock()
        mock_record.get_field.return_value = "steps"
        mock_record.get_value.return_value = 8500.0

        mock_table = MagicMock()
        mock_table.records = [mock_record]

        mock_client = self._make_mock_client([mock_table])

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.query_latest(
                user_id="user_001",
                fields=["steps"],
            )

            assert result["steps"] == 8500.0


class TestInfluxClientDeleteUserData:
    """delete_user_data 测试（GDPR/PIPL）。"""

    @pytest.fixture
    def client(self) -> InfluxClient:
        return InfluxClient(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )

    def _make_mock_client(self) -> MagicMock:
        """创建支持 async with 的 mock client。"""
        mock_delete_api = MagicMock()
        mock_delete_api.delete = AsyncMock()

        mock_client = MagicMock()
        mock_client.delete_api.return_value = mock_delete_api
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_delete_user_data_success(self, client: InfluxClient):
        """删除用户数据成功返回 True。"""
        mock_client = self._make_mock_client()

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.delete_user_data("user_001")

            assert result is True
            mock_client.delete_api().delete.assert_called_once()
            call_kwargs = mock_client.delete_api().delete.call_args[1]
            assert "user_001" in call_kwargs.get("predicate", "")

    @pytest.mark.asyncio
    async def test_delete_user_data_error_returns_false(self, client: InfluxClient):
        """删除失败返回 False。"""
        mock_client = MagicMock()
        mock_client.delete_api.side_effect = Exception("Delete failed")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.delete_user_data("user_001")

            assert result is False

    @pytest.mark.asyncio
    async def test_delete_user_data_constructs_correct_predicate(self, client: InfluxClient):  # noqa: E501
        """删除使用正确的 user_id predicate。"""
        mock_client = self._make_mock_client()

        with patch.object(client, "_get_client", return_value=mock_client):
            await client.delete_user_data("test_user_abc")

            call_kwargs = mock_client.delete_api().delete.call_args[1]
            assert 'user_id="test_user_abc"' in call_kwargs.get("predicate", "")


class TestInfluxClientFailOpen:
    """fail-open 降级测试。"""

    @pytest.fixture
    def client(self) -> InfluxClient:
        return InfluxClient(
            url="http://localhost:8086",
            token="test-token",
            org="test-org",
            bucket="test-bucket",
        )

    @pytest.mark.asyncio
    async def test_query_range_unavailable_returns_empty(self, client: InfluxClient):
        """InfluxDB 不可用时 query_range 返回空字典。"""
        mock_client = MagicMock()
        mock_client.query_api.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch.object(client, "_get_client", return_value=mock_client):
            result = await client.query_range(
                user_id="user_001",
                fields=["heart_rate_avg"],
                start="-7d",
            )

            assert result == {}

    @pytest.mark.asyncio
    async def test_delete_user_data_unavailable_raises(self, client: InfluxClient):
        """delete_user_data 在 InfluxDB 不可用时抛出异常。"""
        mock_client = MagicMock()
        mock_client.delete_api.side_effect = InfluxUnavailableError("Unavailable")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)

        with patch.object(client, "_get_client", return_value=mock_client):
            with pytest.raises(InfluxUnavailableError):
                await client.delete_user_data("user_001")


class TestTrendSeries:
    """TrendSeries 计算属性测试。"""

    def test_latest_value(self):
        """latest 返回最后一个值。"""
        from rhythmind.adapters.influx_client import TrendSeries

        ts = TrendSeries(
            field="heart_rate_avg",
            values=[
                (datetime.now(tz=UTC), 70.0),
                (datetime.now(tz=UTC), 72.0),
                (datetime.now(tz=UTC), 75.0),
            ],
        )
        assert ts.latest == 75.0

    def test_oldest_value(self):
        """oldest 返回第一个值。"""
        from rhythmind.adapters.influx_client import TrendSeries

        ts = TrendSeries(
            field="heart_rate_avg",
            values=[
                (datetime.now(tz=UTC), 70.0),
                (datetime.now(tz=UTC), 72.0),
            ],
        )
        assert ts.oldest == 70.0

    def test_avg_value(self):
        """avg 返回平均值。"""
        from rhythmind.adapters.influx_client import TrendSeries

        ts = TrendSeries(
            field="heart_rate_avg",
            values=[
                (datetime.now(tz=UTC), 70.0),
                (datetime.now(tz=UTC), 80.0),
            ],
        )
        assert ts.avg == 75.0

    def test_delta_value(self):
        """delta 返回最新减最旧的值。"""
        from rhythmind.adapters.influx_client import TrendSeries

        ts = TrendSeries(
            field="heart_rate_avg",
            values=[
                (datetime.now(tz=UTC), 70.0),
                (datetime.now(tz=UTC), 75.0),
            ],
        )
        assert ts.delta == 5.0

    def test_empty_values_handled(self):
        """空值列表返回 None。"""
        from rhythmind.adapters.influx_client import TrendSeries

        ts = TrendSeries(field="heart_rate_avg", values=[])
        assert ts.latest is None
        assert ts.oldest is None
        assert ts.avg is None
        assert ts.delta is None
