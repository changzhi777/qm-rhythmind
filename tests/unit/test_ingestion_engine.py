"""
tests/unit/test_ingestion_engine.py — IngestionEngine 单元测试

策略：mock BaseDataSourceAdapter 和 FactManager，验证引擎编排逻辑
（不依赖真实数据源或 LLM）。
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhythmind.ingestion.base import (
    Activity,
    BodyMetric,
    HealthEvent,
    IngestionResult,
    SleepRecord,
    TrainingMetrics,
    UserProfile,
)
from rhythmind.ingestion.engine import IngestionEngine

_SENTINEL = object()


def _make_adapter(
    *,
    profile_errors: list[str] | None = None,
    profile: UserProfile | None = None,
    activities: list[Activity] | None = None,
    sleep: list[SleepRecord] | None = _SENTINEL,
    body_metrics: list[BodyMetric] | None = None,
    training: TrainingMetrics | None = None,
    events: list[HealthEvent] | None = None,
):
    _DEFAULT_SLEEP = [
        SleepRecord(
            date="2026-01-01", total_hours=8.0, deep_hours=2.0,
            light_hours=3.5, rem_hours=2.5,
        ),
    ]
    if sleep is _SENTINEL:
        sleep = _DEFAULT_SLEEP

    adapter = MagicMock()
    adapter.source_name = "test_source"
    adapter.validate.return_value = profile_errors or []
    adapter.load_profile.return_value = profile or UserProfile(
        gender="male", birth_date="1990-01-01",
        height_cm=175, weight_kg=70,
    )
    adapter.load_activities.return_value = activities or [
        Activity(
            date=datetime(2026, 1, 1), activity_type="running", name="晨跑",
            duration_seconds=1800, distance_meters=5000, avg_hr=150,
        ),
    ]
    adapter.load_sleep.return_value = sleep
    adapter.load_body_metrics.return_value = body_metrics or [
        BodyMetric(date="2026-01-01", vo2_max=48.5, hrv=65, resting_hr=58),
    ]
    adapter.load_training_metrics.return_value = training or TrainingMetrics(
        endurance_score=42, acwr=1.1,
    )
    adapter.load_health_events.return_value = events or []
    return adapter


class TestIngestionEngineIngest:

    @pytest.mark.asyncio
    async def test_full_ingest_success(self, user_id):
        adapter = _make_adapter()

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._adapter = adapter
            engine._user_id = user_id
            engine._fm = AsyncMock()
            engine._fm.write_fact = AsyncMock()

        result = await engine.ingest()

        assert isinstance(result, IngestionResult)
        assert result.profile_records > 0
        assert result.activity_records > 0
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_ingest_validation_failure(self, user_id):
        adapter = _make_adapter(profile_errors=["目录不存在"])

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._adapter = adapter
            engine._user_id = user_id
            engine._fm = AsyncMock()

        result = await engine.ingest()

        assert result.errors == ["目录不存在"]
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_ingest_profile_error_continues(self, user_id):
        adapter = _make_adapter()
        adapter.load_profile.side_effect = Exception("profile parse error")

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._adapter = adapter
            engine._user_id = user_id
            engine._fm = AsyncMock()
            engine._fm.write_fact = AsyncMock()

        result = await engine.ingest()

        assert any("profile" in e for e in result.errors)
        assert result.activity_records > 0

    @pytest.mark.asyncio
    async def test_ingest_no_sleep_data(self, user_id):
        adapter = _make_adapter(sleep=[])

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._adapter = adapter
            engine._user_id = user_id
            engine._fm = AsyncMock()
            engine._fm.write_fact = AsyncMock()

        result = await engine.ingest()
        assert result.sleep_records == 0

    @pytest.mark.asyncio
    async def test_ingest_health_events(self, user_id):
        adapter = _make_adapter(events=[
            HealthEvent(
                date="2026-01-01", event_type="abnormal_hr",
                value=180, threshold=170,
            ),
        ])

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._adapter = adapter
            engine._user_id = user_id
            engine._fm = AsyncMock()
            engine._fm.write_fact = AsyncMock()

        result = await engine.ingest()
        assert result.health_event_records == 1


class TestIngestionEngineAnalyze:

    @pytest.mark.asyncio
    async def test_analyze_no_data(self, user_id):
        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._fm = AsyncMock()
            engine._fm.get_all_current.return_value = []
            engine._model_spec = "omlX://test"

        report = await engine.analyze()
        assert "无可用数据" in report

    @pytest.mark.asyncio
    async def test_analyze_with_facts(self, user_id):
        mock_fact = MagicMock()
        mock_fact.subject = "profile"
        mock_fact.predicate = "weight"
        mock_fact.object_json = 70

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._fm = AsyncMock()
            engine._fm.get_all_current.return_value = [mock_fact]
            engine._fm.write_fact = AsyncMock()
            engine._model_spec = "litellm://test-model"
            engine._user_id = user_id

        with patch("rhythmind.ingestion.engine.adapter_router") as mock_router:
            mock_router.chat = AsyncMock(return_value="这是一份分析报告")
            report = await engine.analyze()

        assert report == "这是一份分析报告"
        engine._fm.write_fact.assert_called_once()


class TestIngestionEngineDashboard:

    @pytest.mark.asyncio
    async def test_get_dashboard_data(self, user_id):
        mock_fact = MagicMock()
        mock_fact.subject = "profile"
        mock_fact.predicate = "weight"
        mock_fact.object_json = 70

        with patch.object(IngestionEngine, "__init__", lambda self, *a, **kw: None):
            engine = IngestionEngine.__new__(IngestionEngine)
            engine._fm = AsyncMock()
            engine._fm.get_all_current.return_value = [mock_fact]

        data = await engine.get_dashboard_data()
        assert "profile.weight" in data
        assert data["profile.weight"] == 70
