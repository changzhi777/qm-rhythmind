"""
tests/unit/test_metrics_agent.py — MetricsProcessor 单元测试

策略：
  - InfluxClient 通过构造器注入 Mock，不依赖真实 InfluxDB
  - MetricsProcessor 不继承 HermesBase，无需 QMD/SkillEngine patch
  - 覆盖：正常写入+查询、InfluxDB 不可用降级、异常检测、负荷分级
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rhythmind.adapters.influx_client import InfluxUnavailableError, TrendSeries
from rhythmind.agents.metrics_agent import _ANOMALY_RULES, MetricsProcessor
from rhythmind.core.compliance.gate import ComplianceLevel
from rhythmind.core.hermes_base import AgentContext, HermesRunResult

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_influx():
    """Mock InfluxClient：write 成功，query_range 返回空趋势。"""
    client = MagicMock()
    client.write_metrics = AsyncMock(return_value=True)
    client.query_range = AsyncMock(return_value={})
    client.query_latest = AsyncMock(return_value={})
    return client


@pytest.fixture
def normal_input() -> dict[str, Any]:
    return {
        "heart_rate_avg": 72.0,
        "heart_rate_max": 165.0,
        "steps": 8500,
        "distance_km": 6.5,
        "calories": 420,
        "sleep_hours": 7.5,
        "hrv": 55.0,
        "sport_type": "running",
        "source": "garmin",
    }


@pytest.fixture
def agent_ctx(normal_input, user_id, session_id) -> AgentContext:
    return AgentContext(
        user_id=user_id,
        session_id=session_id,
        task_type="analyze_metrics",
        input_data=normal_input,
    )


# ── 正常流程 ─────────────────────────────────────────────────────────────────

class TestMetricsProcessorHappyPath:

    @pytest.mark.asyncio
    async def test_run_returns_metrics_analysis(
        self, mock_influx, agent_ctx, user_id, session_id
    ):
        """正常流程：写入成功 + 返回 MetricsAnalysis 结构"""
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result: HermesRunResult = await agent.run(agent_ctx)

        assert result.success is True
        assert result.compliance.level == ComplianceLevel.PASS

        output = result.output
        assert isinstance(output, dict)
        assert "metrics" in output
        assert "trends" in output
        assert "anomalies" in output
        assert "load_level" in output
        assert "write_ok" in output
        assert output["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_write_metrics_called_with_correct_point(
        self, mock_influx, agent_ctx, user_id
    ):
        """InfluxClient.write_metrics 应以正确字段被调用。"""
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        mock_influx.write_metrics.assert_called_once()
        call_args = mock_influx.write_metrics.call_args[0][0]  # MetricPoint
        assert call_args.user_id == user_id
        assert call_args.source == "garmin"
        assert call_args.sport_type == "running"
        assert "heart_rate_avg" in call_args.fields
        assert call_args.fields["heart_rate_avg"] == 72.0

    @pytest.mark.asyncio
    async def test_trends_populated_from_influx(
        self, mock_influx, agent_ctx, user_id
    ):
        """InfluxDB 返回趋势数据时，output["trends"] 应有内容。"""
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        mock_influx.query_range.return_value = {
            "heart_rate_avg": TrendSeries(
                field="heart_rate_avg",
                values=[(ts, 68.0), (ts, 70.0), (ts, 72.0)],
            )
        }

        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        trends = result.output["trends"]
        assert "heart_rate_avg" in trends
        assert trends["heart_rate_avg"]["avg"] == pytest.approx(70.0)
        assert trends["heart_rate_avg"]["latest"] == pytest.approx(72.0)
        assert trends["heart_rate_avg"]["points"] == 3

    @pytest.mark.asyncio
    async def test_confidence_is_1_for_pure_rules(
        self, mock_influx, agent_ctx, user_id
    ):
        """MetricsProcessor 纯规则，置信度应恒为 1.0。"""
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        assert result.compliance.confidence == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_latency_ms_recorded(
        self, mock_influx, agent_ctx, user_id
    ):
        """结果应包含有效的延迟时间。"""
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        assert result.latency_ms > 0
        assert result.agent == "metrics_processor"


# ── InfluxDB 不可用降级 ───────────────────────────────────────────────────────

class TestInfluxUnavailableDegradation:

    @pytest.mark.asyncio
    async def test_influx_write_unavailable_continues(
        self, mock_influx, agent_ctx, user_id
    ):
        """InfluxUnavailableError 写入失败 → 不中断链路，output 仍返回。"""
        mock_influx.write_metrics = AsyncMock(side_effect=InfluxUnavailableError("down"))
        mock_influx.query_range = AsyncMock(side_effect=InfluxUnavailableError("down"))

        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        assert result.success is True  # 降级后仍 PASS
        assert result.output["write_ok"] is False
        assert result.output["influx_available"] is False
        assert result.output["trends"] == {}  # 无趋势数据

    @pytest.mark.asyncio
    async def test_influx_write_ok_but_query_unavailable(
        self, mock_influx, agent_ctx, user_id
    ):
        """写入成功但查询不可用 → write_ok=True，trends 为空。"""
        mock_influx.write_metrics = AsyncMock(return_value=True)
        mock_influx.query_range = AsyncMock(side_effect=InfluxUnavailableError("query down"))

        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(agent_ctx)

        assert result.output["write_ok"] is True
        assert result.output["trends"] == {}


# ── 异常检测（规则引擎）──────────────────────────────────────────────────────

class TestAnomalyDetection:

    @pytest.mark.asyncio
    async def test_no_anomaly_for_normal_data(
        self, mock_influx, user_id, session_id
    ):
        normal_data = {
            "heart_rate_avg": 72, "sleep_hours": 7.5, "hrv": 55,
            "sport_type": "running", "source": "garmin",
        }
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=normal_data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)

        assert result.output["anomalies"] == []
        assert result.compliance.requires_human_review is False

    @pytest.mark.asyncio
    async def test_warn_anomaly_for_borderline_heart_rate(
        self, mock_influx, user_id, session_id
    ):
        """心率略超 WARN 阈值（>120 但 ≤150）→ warn 级异常，不触发人工复核。"""
        data = {"heart_rate_avg": 130, "sport_type": "cycling", "source": "manual"}
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)

        anomalies = result.output["anomalies"]
        assert len(anomalies) == 1
        assert anomalies[0]["field"] == "heart_rate_avg"
        assert anomalies[0]["severity"] == "warn"
        assert result.compliance.requires_human_review is False  # warn 不触发复核

    @pytest.mark.asyncio
    async def test_critical_anomaly_triggers_human_review(
        self, mock_influx, user_id, session_id
    ):
        """心率超 critical 阈值（>150）→ critical 级，requires_human_review=True。"""
        data = {"heart_rate_avg": 160, "sport_type": "running", "source": "apple"}
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)

        anomalies = result.output["anomalies"]
        critical = [a for a in anomalies if a["severity"] == "critical"]
        assert len(critical) >= 1
        assert result.compliance.requires_human_review is True

    @pytest.mark.asyncio
    async def test_multiple_anomalies_detected(
        self, mock_influx, user_id, session_id
    ):
        """多字段异常都应被检出。"""
        data = {
            "heart_rate_avg": 130,   # warn
            "sleep_hours": 2.5,      # warn (< 4)
            "hrv": 7,                # critical (< 10 critical_min = 5, min = 10)
            "sport_type": "general", "source": "manual",
        }
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)

        fields_detected = {a["field"] for a in result.output["anomalies"]}
        assert "heart_rate_avg" in fields_detected
        assert "sleep_hours" in fields_detected
        assert "hrv" in fields_detected


# ── 训练负荷分级 ──────────────────────────────────────────────────────────────

class TestLoadClassification:

    @pytest.mark.asyncio
    async def test_very_low_load(
        self, mock_influx, user_id, session_id
    ):
        """distance_km=2 → very_low"""
        data = {"distance_km": 2.0, "sport_type": "walking", "source": "huawei"}
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)
        assert result.output["load_level"] == "very_low"

    @pytest.mark.asyncio
    async def test_high_load_from_trend_avg(
        self, mock_influx, user_id, session_id
    ):
        """7 日 distance_km 均值 = 10km/day × 7 = 70km → high"""
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        mock_influx.query_range.return_value = {
            "distance_km": TrendSeries(
                field="distance_km",
                values=[(ts, 10.0)] * 7,  # avg = 10.0
            )
        }

        data = {"sport_type": "running", "source": "garmin"}
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)

        # avg 10 × 7 = 70, in [50, 80) → high
        assert result.output["load_level"] == "high"

    @pytest.mark.asyncio
    async def test_zero_distance_is_very_low(
        self, mock_influx, user_id, session_id
    ):
        """距离为 0 或无 → very_low"""
        data = {"sport_type": "yoga", "source": "manual"}
        ctx = AgentContext(user_id=user_id, session_id=session_id,
                           task_type="test", input_data=data)
        agent = MetricsProcessor(user_id=user_id, influx=mock_influx)
        result = await agent.run(ctx)
        assert result.output["load_level"] == "very_low"


# ── 静态方法直接测试（快速单元）────────────────────────────────────────────────

class TestStaticMethods:

    def test_parse_metrics_filters_none(self):
        raw = {"heart_rate_avg": 75, "steps": None, "unknown_field": "ignored"}
        m = MetricsProcessor._parse_metrics(raw)
        assert m["heart_rate_avg"] == 75.0
        assert m["steps"] is None
        assert "unknown_field" not in m

    def test_parse_metrics_coerces_to_float(self):
        raw = {"heart_rate_avg": "72", "distance_km": "5.5"}
        m = MetricsProcessor._parse_metrics(raw)
        assert isinstance(m["heart_rate_avg"], float)
        assert m["distance_km"] == 5.5

    def test_detect_anomalies_empty_metrics(self):
        result = MetricsProcessor._detect_anomalies({k: None for k in _ANOMALY_RULES})
        assert result == []

    def test_classify_load_boundaries(self):
        assert MetricsProcessor._classify_load(0) == "very_low"
        assert MetricsProcessor._classify_load(4.9) == "very_low"
        assert MetricsProcessor._classify_load(5.0) == "low"
        assert MetricsProcessor._classify_load(19.9) == "low"
        assert MetricsProcessor._classify_load(20.0) == "moderate"
        assert MetricsProcessor._classify_load(49.9) == "moderate"
        assert MetricsProcessor._classify_load(50.0) == "high"
        assert MetricsProcessor._classify_load(79.9) == "high"
        assert MetricsProcessor._classify_load(80.0) == "very_high"
        assert MetricsProcessor._classify_load(200.0) == "very_high"
