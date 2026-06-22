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


# ── 内部工具函数 + 边界 case（无文件依赖） ────────────────────────────────

class TestHelperFunctions:
    """_ts_to_date / _extract_location 等纯函数 + load_activities ts 缺失跳过。"""

    def _adapter(self, tmp_path) -> GarminDataSourceAdapter:
        return GarminDataSourceAdapter(str(tmp_path))

    def test_ts_to_date_converts_milliseconds_to_datetime(self, tmp_path):
        """_ts_to_date: int/float 时间戳（毫秒）转 datetime。"""
        adapter = self._adapter(tmp_path)
        result = adapter._ts_to_date(1700000000000)
        assert result is not None
        assert result.year == 2023

    def test_ts_to_date_returns_none_for_non_numeric(self, tmp_path):
        """_ts_to_date: 非 int/float 返回 None（不抛异常）。"""
        adapter = self._adapter(tmp_path)
        assert adapter._ts_to_date("not-a-number") is None
        assert adapter._ts_to_date(None) is None
        assert adapter._ts_to_date([]) is None
        assert adapter._ts_to_date({}) is None

    def test_extract_location_returns_none_for_empty(self, tmp_path):
        """_extract_location: 空字符串/None → None。"""
        adapter = self._adapter(tmp_path)
        assert adapter._extract_location(None) is None
        assert adapter._extract_location("") is None

    def test_extract_location_returns_none_for_single_part(self, tmp_path):
        """_extract_location: 单词 → None（无法取城市）。"""
        adapter = self._adapter(tmp_path)
        assert adapter._extract_location("Beijing") is None
        assert adapter._extract_location("上海") is None

    def test_extract_location_returns_first_part_for_multi_word(self, tmp_path):
        """_extract_location: 多词 → 取第一段（城市名）。"""
        adapter = self._adapter(tmp_path)
        assert adapter._extract_location("Beijing 北京") == "Beijing"
        assert adapter._extract_location("Shenzhen 广东") == "Shenzhen"
        # 多个空格分隔
        assert adapter._extract_location("Shanghai  上海  浦东") == "Shanghai"

    def test_load_activities_skips_entries_without_valid_timestamp(self, tmp_path):
        """load_activities: _ts_to_date 返回 None 的 activity 应被跳过。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # load_activities 读 DI-Connect-Fitness/8616680518888_0_summarizedActivities.json
        # 结构: [{ "summarizedActivitiesExport": [ {...activity...} ] }]
        fitness_file = (
            tmp_path / "DI_CONNECT" / "DI-Connect-Fitness" /
            "8616680518888_0_summarizedActivities.json"
        )
        payload = [{
            "summarizedActivitiesExport": [
                {"startTimeLocal": 1700000000000, "name": "good_run", "activityType": "RUNNING"},
                {"name": "no_timestamp"},  # 缺 startTimeLocal → _ts_to_date None
                {"startTimeLocal": "bad_string", "name": "bad_run"},
                {"startTimeLocal": 1700001000000, "name": "good_run_2", "activityType": "RUNNING"},
            ],
        }]
        _write_json(str(fitness_file), payload)

        result = adapter.load_activities()
        # 3 个保留：good_run + good_run_2 + no_timestamp（beginTimestamp=0 → 1970-01-01）
        # bad_string 被跳过（_ts_to_date 非数字 → None）
        assert len(result) == 3
        names = {a.name for a in result}
        assert {"good_run", "good_run_2", "no_timestamp"} == names


# ── load_profile RUNNING zones + 体重 kg/g 转换 + load_body_metrics ──────────

class TestLoadProfileZones:
    """覆盖 load_profile 中体重转换（line 133）和 RUNNING zones 构造（line 137-147）。"""

    def test_weight_above_200_converted_from_grams(self, tmp_path):
        """体重 > 200 时按 g→kg 转换（line 132-133，典型 Garmin 导出值是 75000g）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # bio 文件名: 11032831_userBioMetricProfileData.json
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_userBioMetricProfileData.json"),
            [{"weight": 75000, "height": 175}],  # 75kg
        )
        profile = adapter.load_profile()
        assert profile.weight_kg == 75.0  # 75000/1000

    def test_weight_below_200_not_converted(self, tmp_path):
        """体重 ≤ 200 时直接用（line 132-133，kg 值不转换）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_userBioMetricProfileData.json"),
            [{"weight": 75, "height": 175}],
        )
        profile = adapter.load_profile()
        assert profile.weight_kg == 75

    def test_running_zones_constructed_from_fitness_data(self, tmp_path):
        """load_profile: hr_zones 中 sport=RUNNING 的条目构造 5 zone（line 137-147）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # bio（必需）
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_userBioMetricProfileData.json"),
            [{"weight": 75, "height": 175}],
        )
        # heartRateZones.json：sport=RUNNING 条目带各 zone floor
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_heartRateZones.json"),
            [{
                "sport": "RUNNING",
                "zone1Floor": 100, "zone2Floor": 130, "zone3Floor": 150,
                "zone4Floor": 170, "zone5Floor": 190,
                "restingHeartRateUsed": 60, "maxHeartRateUsed": 195,
            }],
        )
        profile = adapter.load_profile()

        # 5 zone 边界正确
        assert profile.hr_zones["Z1"] == (100, 130)
        assert profile.hr_zones["Z2"] == (130, 150)
        assert profile.hr_zones["Z3"] == (150, 170)
        assert profile.hr_zones["Z4"] == (170, 190)
        assert profile.hr_zones["Z5"] == (190, 220)  # Z5 固定 220
        # resting_hr / max_hr
        assert profile.resting_hr == 60
        assert profile.max_hr == 195

    def test_non_running_zones_ignored(self, tmp_path):
        """hr_zones 中 sport≠RUNNING 的条目应被忽略（line 137 条件过滤）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_userBioMetricProfileData.json"),
            [{"weight": 75, "height": 175}],
        )
        # 只放 CYCLING 的 hr_zones（RUNNING 缺失）
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_heartRateZones.json"),
            [{
                "sport": "CYCLING",
                "zone1Floor": 100, "zone2Floor": 130, "zone3Floor": 150,
                "zone4Floor": 170, "zone5Floor": 190,
                "restingHeartRateUsed": 60, "maxHeartRateUsed": 195,
            }],
        )
        profile = adapter.load_profile()
        # 没有 RUNNING zones，hr_zones 留空 dict
        assert profile.hr_zones == {}
        # resting_hr/max_hr 不被设置（loop 找不到 RUNNING 条目，不进 break）
        assert profile.resting_hr is None
        assert profile.max_hr is None


class TestLoadBodyMetrics:
    """覆盖 load_body_metrics 三段（line 217-254）。"""

    def test_vo2_max_from_metrics_max_met_data(self, tmp_path):
        """load_body_metrics: MetricsMaxMetData 数值 cal_date 转 ISO date。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # _load_all_metrics glob: MetricsMaxMetData_*.json（prefix 开头）
        vo2_data = [
            {"calendarDate": 1700000000000, "vo2MaxValue": 48.5},
            {"calendarDate": 1700100000000, "vo2MaxValue": 49.1},
        ]
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Metrics" / "MetricsMaxMetData_12345.json"),
            vo2_data,
        )

        metrics = adapter.load_body_metrics()
        vo2_metrics = [m for m in metrics if m.vo2_max is not None]
        assert len(vo2_metrics) == 2
        # 第一个 vo2 日期应转 ISO YYYY-MM-DD 格式（具体日期因时区而异）
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", vo2_metrics[0].date)
        assert vo2_metrics[0].vo2_max == 48.5

    def test_vo2_max_string_cal_date_truncated_to_10_chars(self, tmp_path):
        """load_body_metrics: cal_date 是字符串时截前 10 字符（line 226 else 分支）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Metrics" / "MetricsMaxMetData_12345.json"),
            [{"calendarDate": "2023-11-14T08:00:00Z", "vo2MaxValue": 48.0}],
        )

        metrics = adapter.load_body_metrics()
        vo2_metrics = [m for m in metrics if m.vo2_max is not None]
        assert len(vo2_metrics) == 1
        assert vo2_metrics[0].date == "2023-11-14"  # 截前 10 字符

    def test_fitness_age_from_user_bio_metrics(self, tmp_path):
        """load_body_metrics: userBioMetrics.json 提供 fitness_age（line 232-239）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # fitness_age 读 userBioMetrics.json（与 bio_profile 同文件但不同 key）
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_userBioMetrics.json"),
            [
                {"asOfDateGmt": "2023-11-14T08:00:00Z", "currentBioAge": 32.5},
            ],
        )

        metrics = adapter.load_body_metrics()
        age_metrics = [m for m in metrics if m.fitness_age is not None]
        assert len(age_metrics) == 1
        assert age_metrics[0].fitness_age == 32.5
        assert age_metrics[0].date == "2023-11-14"  # 截前 10 字符

    def test_hrv_and_resting_hr_from_health_status(self, tmp_path):
        """load_body_metrics: healthStatus 文件提供 HRV + RestingHR（line 241-252）。"""
        _make_garmin_dir(str(tmp_path))
        adapter = GarminDataSourceAdapter(str(tmp_path))

        # _load_all_wellness("*healthStatus*.json") glob 匹配
        _write_json(
            str(tmp_path / "DI_CONNECT" / "DI-Connect-Wellness" / "11032831_healthStatus.json"),
            [{
                "calendarDate": "2023-11-14",
                "metrics": [
                    {"type": "HRV", "value": 55.0},
                    {"type": "HR", "value": 60.0},
                ],
            }],
        )

        metrics = adapter.load_body_metrics()
        hrv_metrics = [m for m in metrics if m.hrv is not None]
        assert len(hrv_metrics) == 1
        assert hrv_metrics[0].hrv == 55.0
        assert hrv_metrics[0].resting_hr == 60.0
        assert hrv_metrics[0].date == "2023-11-14"
