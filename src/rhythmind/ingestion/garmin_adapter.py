"""
ingestion/garmin_adapter.py — Garmin Connect 数据导出包适配器

解析 Garmin Connect 数据导出目录中的 JSON 文件，
转换为统一的 BaseDataSourceAdapter 数据模型。

数据目录结构：
  GarminExport/
  ├── DI_CONNECT/DI-Connect-Fitness/     # 活动
  ├── DI_CONNECT/DI-Connect-Metrics/     # 训练指标
  ├── DI_CONNECT/DI-Connect-Wellness/    # 睡眠/HRV
  ├── DI_CONNECT/DI-Connect-User/        # 用户资料
  └── customer_data/                     # 客户信息
"""
from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime

from rhythmind.ingestion.base import (
    Activity,
    BaseDataSourceAdapter,
    BodyMetric,
    HealthEvent,
    SleepRecord,
    TrainingMetrics,
    UserProfile,
)

logger = logging.getLogger(__name__)


class GarminDataSourceAdapter(BaseDataSourceAdapter):
    """Garmin Connect 数据导出包适配器。"""

    def __init__(self, data_dir: str) -> None:
        self._dir = data_dir
        self._user_id = "garmin_user_001"

    @property
    def source_name(self) -> str:
        return "garmin"

    def validate(self) -> list[str]:
        errors = []
        if not os.path.isdir(self._dir):
            errors.append(f"数据目录不存在: {self._dir}")
            return errors
        required = [
            "DI_CONNECT/DI-Connect-Fitness",
            "DI_CONNECT/DI-Connect-User",
        ]
        for sub in required:
            if not os.path.isdir(os.path.join(self._dir, sub)):
                errors.append(f"缺少必要子目录: {sub}")
        return errors

    # ── 内部工具 ──────────────────────────────────────────────────────────

    def _load_json(self, *parts: str) -> list | dict | None:
        path = os.path.join(self._dir, *parts)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_all_metrics(self, prefix: str) -> list[dict]:
        files = sorted(glob.glob(
            os.path.join(self._dir, "DI_CONNECT", "DI-Connect-Metrics", f"{prefix}_*.json")
        ))
        records = []
        for f in files:
            try:
                data = json.load(open(f, "r", encoding="utf-8"))
                if isinstance(data, list):
                    records.extend(data)
            except Exception:
                pass
        return records

    def _load_all_wellness(self, pattern: str) -> list[dict]:
        files = sorted(glob.glob(
            os.path.join(self._dir, "DI_CONNECT", "DI-Connect-Wellness", pattern)
        ))
        records = []
        for f in files:
            try:
                data = json.load(open(f, "r", encoding="utf-8"))
                if isinstance(data, list):
                    records.extend(data)
            except Exception:
                pass
        return records

    def _ts_to_date(self, ts) -> datetime | None:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000)
        return None

    def _extract_location(self, name: str | None) -> str | None:
        if not name:
            return None
        parts = name.strip().split()
        if len(parts) > 1:
            return parts[0]
        return None

    # ── 接口实现 ──────────────────────────────────────────────────────────

    def load_profile(self) -> UserProfile:
        profile = self._load_json("DI_CONNECT", "DI-Connect-User", "user_profile.json") or {}
        bio_data = self._load_json(
            "DI_CONNECT", "DI-Connect-Wellness", "11032831_userBioMetricProfileData.json"
        ) or [{}]
        bio = bio_data[0] if bio_data else {}
        hr_zones = self._load_json(
            "DI_CONNECT", "DI-Connect-Wellness", "11032831_heartRateZones.json"
        ) or []

        weight = bio.get("weight", 0)
        if weight > 200:
            weight = weight / 1000

        zones: dict[str, tuple[int, int]] = {}
        for z in hr_zones:
            if z.get("sport") == "RUNNING":
                zones = {
                    "Z1": (z.get("zone1Floor", 0), z.get("zone2Floor", 0)),
                    "Z2": (z.get("zone2Floor", 0), z.get("zone3Floor", 0)),
                    "Z3": (z.get("zone3Floor", 0), z.get("zone4Floor", 0)),
                    "Z4": (z.get("zone4Floor", 0), z.get("zone5Floor", 0)),
                    "Z5": (z.get("zone5Floor", 0), 220),
                }
                resting_hr = z.get("restingHeartRateUsed")
                max_hr = z.get("maxHeartRateUsed")
                break

        return UserProfile(
            gender=profile.get("gender", "UNKNOWN"),
            birth_date=profile.get("birthDate", "2000-01-01"),
            height_cm=bio.get("height", 170),
            weight_kg=weight,
            vo2_max=bio.get("vo2Max"),
            lactate_threshold_hr=bio.get("lactateThresholdHeartRate"),
            ftp_watts=bio.get("functionalThresholdPower"),
            resting_hr=resting_hr if 'resting_hr' in dir() else None,
            max_hr=max_hr if 'max_hr' in dir() else None,
            hr_zones=zones,
        )

    def load_activities(self) -> list[Activity]:
        raw = self._load_json(
            "DI_CONNECT", "DI-Connect-Fitness",
            "8616680518888_0_summarizedActivities.json"
        )
        if not raw:
            return []
        acts = raw[0].get("summarizedActivitiesExport", [])

        results = []
        for a in acts:
            ts = self._ts_to_date(a.get("startTimeLocal", a.get("beginTimestamp", 0)))
            if not ts:
                continue
            results.append(Activity(
                date=ts,
                activity_type=a.get("activityType", "unknown"),
                name=a.get("name", ""),
                duration_seconds=(a.get("duration", 0) or 0) / 1000,
                distance_meters=(a.get("distance", 0) or 0) / 100,
                avg_hr=a.get("avgHr"),
                max_hr=a.get("maxHr"),
                calories=a.get("calories"),
                elevation_gain_m=(a.get("elevationGain", 0) or 0) / 100,
                avg_cadence=a.get("avgRunCadence"),
                steps=a.get("steps"),
                avg_speed_ms=(a.get("avgSpeed", 0) or 0) * 10,
                avg_power=a.get("avgPower"),
                aerobic_te=a.get("aerobicTrainingEffect"),
                location=self._extract_location(a.get("name")),
            ))
        return results

    def load_sleep(self) -> list[SleepRecord]:
        raw = self._load_all_wellness("*sleepData*.json")
        results = []
        for s in raw:
            deep = s.get("deepSleepSeconds", 0) or 0
            light = s.get("lightSleepSeconds", 0) or 0
            rem = s.get("remSleepSeconds", 0) or 0
            awake = s.get("awakeSleepSeconds", 0) or 0
            total = deep + light + rem
            if total < 10800:
                continue
            results.append(SleepRecord(
                date=s.get("calendarDate", ""),
                total_hours=total / 3600,
                deep_hours=deep / 3600,
                light_hours=light / 3600,
                rem_hours=rem / 3600,
                awake_hours=awake / 3600,
            ))
        return results

    def load_body_metrics(self) -> list[BodyMetric]:
        metrics: list[BodyMetric] = []

        # VO2 Max
        for m in self._load_all_metrics("MetricsMaxMetData"):
            cal_date = m.get("calendarDate")
            if isinstance(cal_date, (int, float)):
                date_str = self._ts_to_date(cal_date).strftime("%Y-%m-%d")
            else:
                date_str = str(cal_date)[:10]
            metrics.append(BodyMetric(
                date=date_str,
                vo2_max=m.get("vo2MaxValue"),
            ))

        # Fitness Age
        for ba in self._load_json(
            "DI_CONNECT", "DI-Connect-Wellness", "11032831_userBioMetrics.json"
        ) or []:
            metrics.append(BodyMetric(
                date=ba.get("asOfDateGmt", "")[:10],
                fitness_age=ba.get("currentBioAge"),
            ))

        # HRV + Resting HR
        for h in self._load_all_wellness("*healthStatus*.json"):
            date_str = h.get("calendarDate", "")
            hrv = None
            rhr = None
            for m_item in h.get("metrics", []):
                if m_item.get("type") == "HRV":
                    hrv = m_item.get("value")
                elif m_item.get("type") == "HR":
                    rhr = m_item.get("value")
            if hrv or rhr:
                metrics.append(BodyMetric(date=date_str, hrv=hrv, resting_hr=rhr))

        return metrics

    def load_training_metrics(self) -> TrainingMetrics:
        # Endurance
        endurance = self._load_all_metrics("EnduranceScore")
        latest_e = endurance[-1] if endurance else {}

        # Training Load
        acute = self._load_all_metrics("MetricsAcuteTrainingLoad")
        latest_atl = acute[-1] if acute else {}

        # Training Readiness
        readiness = self._load_all_metrics("TrainingReadinessDTO")
        latest_tr = readiness[-1] if readiness else {}

        # Race Predictions
        race = self._load_all_metrics("RunRacePredictions")
        latest_race = race[-1] if race else {}

        # Hill Score
        hill = self._load_all_metrics("HillScore")
        latest_hill = hill[-1] if hill else {}

        class_map = {1: "差", 2: "一般", 3: "良好", 4: "优秀", 5: "卓越"}

        return TrainingMetrics(
            endurance_score=latest_e.get("overallScore"),
            endurance_classification=class_map.get(latest_e.get("classification")),
            hill_score=latest_hill.get("overallScore"),
            acute_load=latest_atl.get("dailyTrainingLoadAcute"),
            chronic_load=latest_atl.get("dailyTrainingLoadChronic"),
            acwr=latest_atl.get("dailyAcuteChronicWorkloadRatio"),
            acwr_status=latest_atl.get("acwrStatus"),
            training_readiness_score=latest_tr.get("score"),
            training_readiness_level=latest_tr.get("level"),
            race_predictions={
                "5k": latest_race.get("raceTime5K", 0),
                "10k": latest_race.get("raceTime10K", 0),
                "half": latest_race.get("raceTimeHalf", 0),
                "marathon": latest_race.get("raceTimeMarathon", 0),
            },
        )

    def load_health_events(self) -> list[HealthEvent]:
        raw = self._load_all_wellness("*AbnormalHr*.json")
        results = []
        for e in raw:
            results.append(HealthEvent(
                date=e.get("calendarDate", ""),
                event_type="abnormal_hr",
                value=e.get("abnormalHrValue", 0),
                threshold=e.get("abnormalHrThresholdValue", 0),
                description=f"心率 {e.get('abnormalHrValue')} bpm (阈值 {e.get('abnormalHrThresholdValue')} bpm)",
            ))
        return results
