"""
tests/unit/test_ingestion_base.py — ingestion/base.py 数据模型 + ABC 测试

覆盖：UserProfile / Activity / SleepRecord / BodyMetric / TrainingMetrics /
      HealthEvent / IngestionResult 的属性与计算逻辑。
"""
from __future__ import annotations

from datetime import datetime

from rhythmind.ingestion.base import (
    Activity,
    BodyMetric,
    HealthEvent,
    IngestionResult,
    SleepRecord,
    TrainingMetrics,
    UserProfile,
)


class TestUserProfile:

    def test_bmi_calculation(self):
        p = UserProfile(
            gender="male", birth_date="1990-06-15",
            height_cm=175, weight_kg=70,
        )
        assert abs(p.bmi - 22.9) < 0.1

    def test_age_calculation(self):
        p = UserProfile(
            gender="male", birth_date="1990-01-01",
            height_cm=175, weight_kg=70,
        )
        assert p.age >= 35

    def test_default_optional_fields(self):
        p = UserProfile(
            gender="female", birth_date="2000-01-01",
            height_cm=160, weight_kg=55,
        )
        assert p.vo2_max is None
        assert p.resting_hr is None
        assert p.max_hr is None
        assert p.hr_zones == {}

    def test_hr_zones_present(self):
        zones = {"Z1": (100, 130), "Z2": (130, 150)}
        p = UserProfile(
            gender="male", birth_date="1990-01-01",
            height_cm=180, weight_kg=75, hr_zones=zones,
        )
        assert p.hr_zones["Z1"] == (100, 130)


class TestActivity:

    def test_pace_min_per_km(self):
        a = Activity(
            date=datetime(2026, 1, 1), activity_type="running", name="晨跑",
            duration_seconds=1800, distance_meters=5000,
        )
        assert abs(a.pace_min_per_km - 6.0) < 0.01

    def test_pace_zero_distance(self):
        a = Activity(
            date=datetime(2026, 1, 1), activity_type="yoga", name="瑜伽",
            duration_seconds=1800, distance_meters=0,
        )
        assert a.pace_min_per_km is None

    def test_distance_km(self):
        a = Activity(
            date=datetime(2026, 1, 1), activity_type="running", name="跑",
            duration_seconds=1800, distance_meters=10000,
        )
        assert a.distance_km == 10.0

    def test_optional_fields_default_none(self):
        a = Activity(
            date=datetime(2026, 1, 1), activity_type="cycling", name="骑行",
            duration_seconds=3600, distance_meters=30000,
        )
        assert a.avg_hr is None
        assert a.max_hr is None
        assert a.calories is None


class TestSleepRecord:

    def test_deep_pct(self):
        s = SleepRecord(
            date="2026-01-01", total_hours=8.0, deep_hours=2.0,
            light_hours=3.5, rem_hours=2.5,
        )
        assert abs(s.deep_pct - 25.0) < 0.1

    def test_deep_pct_zero_total(self):
        s = SleepRecord(
            date="2026-01-01", total_hours=0, deep_hours=0,
            light_hours=0, rem_hours=0,
        )
        assert s.deep_pct == 0


class TestBodyMetric:

    def test_all_none_optional(self):
        m = BodyMetric(date="2026-01-01")
        assert m.vo2_max is None
        assert m.fitness_age is None
        assert m.hrv is None

    def test_with_values(self):
        m = BodyMetric(date="2026-01-01", vo2_max=48.5, hrv=65)
        assert m.vo2_max == 48.5
        assert m.hrv == 65


class TestTrainingMetrics:

    def test_defaults(self):
        t = TrainingMetrics()
        assert t.endurance_score is None
        assert t.acwr is None
        assert t.race_predictions == {}

    def test_with_race_predictions(self):
        t = TrainingMetrics(race_predictions={"5k": 1200, "10k": 2700})
        assert t.race_predictions["5k"] == 1200


class TestHealthEvent:

    def test_creation(self):
        e = HealthEvent(
            date="2026-01-01", event_type="abnormal_hr",
            value=180, threshold=170,
            description="心率异常",
        )
        assert e.value == 180
        assert e.description == "心率异常"


class TestIngestionResult:

    def test_total_zero(self):
        r = IngestionResult()
        assert r.total == 0
        assert r.errors == []

    def test_total_with_records(self):
        r = IngestionResult(
            profile_records=9, activity_records=3,
            sleep_records=1, body_metric_records=1,
        )
        assert r.total == 14

    def test_errors_list(self):
        r = IngestionResult(errors=["profile: missing field", "sleep: bad data"])
        assert len(r.errors) == 2
