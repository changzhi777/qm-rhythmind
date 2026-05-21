"""
tests/unit/test_garmin_adapter.py — GarminDataSourceAdapter 单元测试

策略：用临时目录模拟 Garmin Connect 数据导出目录结构，
测试文件解析、字段映射、错误处理。
"""
from __future__ import annotations

import json
import os

import pytest

from rhythmind.ingestion.garmin_adapter import GarminDataSourceAdapter


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _make_garmin_dir(tmp: str) -> dict[str, str]:
    """创建最小 Garmin 导出目录结构，返回路径映射。"""
    dirs = {
        "fitness": os.path.join(tmp, "DI_CONNECT", "DI-Connect-Fitness"),
        "user": os.path.join(tmp, "DI_CONNECT", "DI-Connect-User"),
        "metrics": os.path.join(tmp, "DI_CONNECT", "DI-Connect-Metrics"),
        "wellness": os.path.join(tmp, "DI_CONNECT", "DI-Connect-Wellness"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    return dirs


class TestGarminAdapterValidation:

    def test_validate_missing_dir(self):
        adapter = GarminDataSourceAdapter("/nonexistent/path")
        errors = adapter.validate()
        assert len(errors) > 0
        assert "不存在" in errors[0]

    def test_validate_missing_subdirs(self, tmp_path):
        os.makedirs(tmp_path / "DI_CONNECT" / "DI-Connect-Fitness")
        adapter = GarminDataSourceAdapter(str(tmp_path))
        errors = adapter.validate()
        assert any("DI-Connect-User" in e for e in errors)

    def test_validate_ok(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        errors = adapter.validate()
        assert errors == []


class TestGarminAdapterLoadProfile:

    @pytest.mark.asyncio
    async def test_load_profile_basic(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["user"], "user_profile.json"),
            {"gender": "Male", "birthDate": "1990-06-15"},
        )
        _write_json(
            os.path.join(dirs["wellness"], "11032831_userBioMetricProfileData.json"),
            [{"height": 175, "weight": 70, "vo2Max": 48.5}],
        )
        _write_json(
            os.path.join(dirs["wellness"], "11032831_heartRateZones.json"),
            [],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        profile = adapter.load_profile()

        assert profile.gender == "Male"
        assert profile.height_cm == 175
        assert profile.weight_kg == 70
        assert profile.vo2_max == 48.5

    def test_load_profile_missing_files(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        profile = adapter.load_profile()
        assert profile.gender == "UNKNOWN"
        assert profile.height_cm == 170


class TestGarminAdapterLoadActivities:

    def test_load_activities(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["fitness"], "8616680518888_0_summarizedActivities.json"),
            [{"summarizedActivitiesExport": [
                {
                    "startTimeLocal": 1735689600000,
                    "activityType": "running",
                    "name": "晨跑",
                    "duration": 1800000,
                    "distance": 500000,
                    "avgHr": 150,
                    "maxHr": 175,
                    "calories": 350,
                },
            ]}],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        activities = adapter.load_activities()

        assert len(activities) == 1
        assert activities[0].activity_type == "running"
        assert activities[0].avg_hr == 150
        assert activities[0].distance_km == 5.0

    def test_load_activities_empty(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        activities = adapter.load_activities()
        assert activities == []


class TestGarminAdapterLoadSleep:

    def test_load_sleep(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["wellness"], "sleepData_2026.json"),
            [{"calendarDate": "2026-01-01",
              "deepSleepSeconds": 7200, "lightSleepSeconds": 12600,
              "remSleepSeconds": 9000, "awakeSleepSeconds": 1800}],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        sleep = adapter.load_sleep()

        assert len(sleep) == 1
        assert abs(sleep[0].total_hours - 8.0) < 0.1

    def test_load_sleep_filters_short(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["wellness"], "sleepData_2026.json"),
            [{"deepSleepSeconds": 600, "lightSleepSeconds": 1800,
              "remSleepSeconds": 600}],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        sleep = adapter.load_sleep()
        assert sleep == []


class TestGarminAdapterLoadTrainingMetrics:

    def test_load_training_metrics(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["metrics"], "EnduranceScore_2026.json"),
            [{"overallScore": 42, "classification": 3}],
        )
        _write_json(
            os.path.join(dirs["metrics"], "MetricsAcuteTrainingLoad_2026.json"),
            [{"dailyTrainingLoadAcute": 100, "dailyTrainingLoadChronic": 90,
              "dailyAcuteChronicWorkloadRatio": 1.1, "acwrStatus": "optimal"}],
        )
        _write_json(
            os.path.join(dirs["metrics"], "TrainingReadinessDTO_2026.json"),
            [{"score": 85, "level": "高"}],
        )
        _write_json(
            os.path.join(dirs["metrics"], "RunRacePredictions_2026.json"),
            [{"raceTime5K": 1200, "raceTime10K": 2700}],
        )
        _write_json(
            os.path.join(dirs["metrics"], "HillScore_2026.json"),
            [{"overallScore": 78}],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        tm = adapter.load_training_metrics()

        assert tm.endurance_score == 42
        assert tm.acwr == 1.1
        assert tm.training_readiness_score == 85
        assert tm.race_predictions["5k"] == 1200

    def test_load_training_metrics_empty(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        tm = adapter.load_training_metrics()
        assert tm.endurance_score is None
        assert tm.race_predictions == {"5k": 0, "10k": 0, "half": 0, "marathon": 0}


class TestGarminAdapterSourceName:

    def test_source_name(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        assert adapter.source_name == "garmin"


class TestGarminAdapterHealthEvents:

    def test_load_health_events(self, tmp_path):
        dirs = _make_garmin_dir(str(tmp_path))

        _write_json(
            os.path.join(dirs["wellness"], "AbnormalHr_2026.json"),
            [{"calendarDate": "2026-01-01",
              "abnormalHrValue": 180, "abnormalHrThresholdValue": 170}],
        )

        adapter = GarminDataSourceAdapter(str(tmp_path))
        events = adapter.load_health_events()

        assert len(events) == 1
        assert events[0].value == 180
        assert events[0].event_type == "abnormal_hr"

    def test_load_health_events_empty(self, tmp_path):
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))
        events = adapter.load_health_events()
        assert events == []
