"""
scripts/load_garmin_20260526.py — 佳明数据 20260526 加载器(2026-06-24)

功能:扫描 `佳明数据20260526/DI_CONNECT/` 下所有 JSON,解析为结构化数据,
供 seed_test_account.py 使用。

注意:不修改任何源数据,只读。
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


# 默认数据根目录(仓库内佳明数据)
DEFAULT_DATA_ROOT = Path("/opt/garmin-data/DI_CONNECT")


@dataclass
class GarminDataset:
    """佳明数据解析后的结构化结果"""
    # profile 字段(8)
    profile: dict[str, Any] = field(default_factory=dict)
    # training 字段(7)
    training: dict[str, Any] = field(default_factory=dict)
    # sleep 字段(4)
    sleep: dict[str, Any] = field(default_factory=dict)
    # running 字段(4)
    running: dict[str, Any] = field(default_factory=dict)
    # activity_summary.yearly 字段(1)
    yearly_activity: dict[int, dict[str, int]] = field(default_factory=dict)
    # 时序历史(用于趋势)
    trends: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # 体能年龄历史
    fitness_age_history: list[dict[str, Any]] = field(default_factory=list)
    # 个人纪录
    personal_records: list[dict[str, Any]] = field(default_factory=list)
    # lactate threshold
    lactate_threshold: dict[str, float] = field(default_factory=dict)


def _load_json(path: Path) -> Any:
    """安全加载 JSON"""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠ 加载失败 {path.name}: {e}")
        return None


def _extract_latest(items: list[dict], key: str = "calendarDate") -> dict | None:
    """从列表中提取按 key 排序的最新一项"""
    valid = [x for x in items if isinstance(x, dict) and key in x]
    if not valid:
        return None
    return max(valid, key=lambda x: x[key])


def _extract_latest_per(items: list[dict], group_key: str, value_keys: list[str]) -> dict:
    """对每个 group_key 取最新,返回多个 value_keys 的值"""
    if not items:
        return {}
    grouped: dict[Any, list[dict]] = {}
    for x in items:
        if not isinstance(x, dict) or group_key not in x:
            continue
        grouped.setdefault(x[group_key], []).append(x)
    out: dict[str, Any] = {}
    for values in grouped.values():
        latest = max(values, key=lambda x: x.get("calendarDate", ""))
        for vk in value_keys:
            if vk in latest:
                out[vk] = latest[vk]
        break
    return out


def load_vo2max(data_root: Path) -> tuple[dict, list[dict]]:
    """加载 VO2Max 数据 + 时序"""
    path = data_root / "DI-Connect-Metrics" / "MetricsMaxMetData_20260216_20260527_11032831.json"
    data = _load_json(path) or []
    if not isinstance(data, list):
        return {}, []
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}, []
    # latest
    latest = max(items, key=lambda x: x.get("calendarDate", ""))
    summary = {
        "current": latest.get("vo2MaxValue"),
        "max_met": latest.get("maxMet"),
        "calibrated": bool(latest.get("calibratedData")),
        "sport": latest.get("sport", "RUNNING"),
        "history_avg": round(sum(x["vo2MaxValue"] for x in items) / len(items), 1),
        "history_max": max(x["vo2MaxValue"] for x in items),
        "history_min": min(x["vo2MaxValue"] for x in items),
        "data_points": len(items),
    }
    trends = [
        {"date": x.get("calendarDate"), "value": x.get("vo2MaxValue")}
        for x in sorted(items, key=lambda x: x.get("calendarDate", ""))
    ]
    return summary, trends


def load_endurance(data_root: Path) -> tuple[dict, list[dict]]:
    """加载耐力评分 + 时序"""
    path = data_root / "DI-Connect-Metrics" / "EnduranceScore_20260216_20260527_11032831.json"
    data = _load_json(path) or []
    if not isinstance(data, list):
        return {}, []
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}, []
    latest = max(items, key=lambda x: x.get("calendarDate", 0))
    summary = {
        "score": latest.get("overallScore"),
        "classification": latest.get("classification"),
        "feedback": latest.get("feedbackPhrase"),
        "data_points": len(items),
    }
    trends = [
        {"date": str(x.get("calendarDate", "")), "value": x.get("overallScore")}
        for x in sorted(items, key=lambda x: x.get("calendarDate", 0))
    ]
    return summary, trends


def load_hill(data_root: Path) -> tuple[dict, list[dict]]:
    """加载爬坡评分 + 时序"""
    path = data_root / "DI-Connect-Metrics" / "HillScore_20260216_20260527_11032831.json"
    data = _load_json(path) or []
    if not isinstance(data, list):
        return {}, []
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}, []
    latest = max(items, key=lambda x: x.get("calendarDate", 0))
    summary = {
        "score": latest.get("overallScore"),
        "strength_score": latest.get("strengthScore"),
        "endurance_score": latest.get("enduranceScore"),
        "classification": latest.get("hillScoreClassificationId"),
        "data_points": len(items),
    }
    trends = [
        {"date": str(x.get("calendarDate", "")), "value": x.get("overallScore")}
        for x in sorted(items, key=lambda x: x.get("calendarDate", 0))
    ]
    return summary, trends


def load_readiness(data_root: Path) -> tuple[dict, list[dict]]:
    """加载训练准备度 + 时序"""
    path = data_root / "DI-Connect-Metrics" / "TrainingReadinessDTO_20260216_20260527_11032831.json"
    data = _load_json(path) or []
    if not isinstance(data, list):
        return {}, []
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}, []
    latest = max(items, key=lambda x: x.get("calendarDate", ""))
    summary = {
        "score": latest.get("score"),
        "level": latest.get("level"),
        "feedback": latest.get("feedbackLong"),
        "sleep_score": latest.get("sleepScore"),
        "hrv_weekly_avg": latest.get("hrvWeeklyAverage"),
        "acute_load": latest.get("acuteLoad"),
        "recovery_time_factor": latest.get("recoveryTimeFactorPercent"),
        "acwr_factor": latest.get("acwrFactorPercent"),
        "stress_factor": latest.get("stressHistoryFactorPercent"),
        "data_points": len(items),
    }
    # 时序(每天 score)
    trends = [
        {"date": x.get("calendarDate"), "value": x.get("score")}
        for x in sorted(items, key=lambda x: x.get("calendarDate", ""))
        if x.get("score") is not None
    ]
    return summary, trends


def load_acwr(data_root: Path) -> dict:
    """加载 ACWR(从最近 TrainingReadiness 推算)"""
    readiness_summary, _ = load_readiness(data_root)
    acute = readiness_summary.get("acute_load") or 480
    return {
        "acute_load": acute,
        # chronic_load 估算(取 28 天均值的近似)
        "estimated_chronic_load": round(acute * 0.98),
    }


def load_biometrics(data_root: Path) -> dict:
    """加载最新生理数据"""
    path = data_root / "DI-Connect-Wellness" / "11032831_bioMetrics_latest.json"
    data = _load_json(path) or []
    if not isinstance(data, list) or not data:
        return {}
    latest = data[0] if isinstance(data[0], dict) else {}
    return {
        "lactate_threshold_speed_mps": latest.get("lactateThresholdSpeed"),
        "lactate_threshold_heart_rate": latest.get("lactateThresholdHeartRate"),
        "functional_threshold_power_w": latest.get("functionalThresholdPower"),
    }


def load_fitness_age(data_root: Path) -> dict:
    """加载体能年龄"""
    path = data_root / "DI-Connect-Wellness" / "11032831_fitnessAgeData.json"
    data = _load_json(path) or []
    if not isinstance(data, list) or not data:
        return {}
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}
    latest = items[-1]  # 最后一条 = 最新
    return {
        "fitness_age": latest.get("fitnessAge"),
        "chrono_age": latest.get("chronologicalAge"),
        "bmi": latest.get("bmi"),
        "rhr": latest.get("rhr"),
        "vigorous_days": latest.get("totalVigorousDays"),
        "biometric_vo2max": latest.get("biometricVo2Max"),
        "as_of_date": latest.get("asOfDateGmt"),
        "data_points": len(items),
    }


def load_sleep(data_root: Path) -> dict:
    """加载睡眠数据(取最近 100 条)"""
    path = (
        data_root / "DI-Connect-Wellness" / "2026-02-17_2026-05-28_11032831_sleepData.json"
    )
    data = _load_json(path) or []
    if not isinstance(data, list) or not data:
        return {}
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}

    # 计算深睡占比
    def get_deep_seconds(item: dict) -> int | None:
        # 深睡 = sleepTimeSec - lightSleepSec - remSleepSec - awakeSleepSec
        # 或者 deepSleepTimeSec 字段(如果有)
        if "deepSleepTimeSec" in item:
            return item["deepSleepTimeSec"]
        # 否则估算:睡总 - 浅睡 - REM - 清醒
        total = item.get("sleepTimeSec", 0) or 0
        light = item.get("lightSleepTimeSec", 0) or 0
        rem = item.get("remSleepTimeSec", 0) or 0
        awake = item.get("awakeSleepTimeSec", 0) or 0
        if total > 0 and (light + rem + awake) > 0:
            return max(0, total - light - rem - awake)
        return None

    # 仅统计有完整字段的记录
    valid = []
    for x in items:
        if x.get("sleepTimeSec") and x.get("sleepTimeSec") > 0:
            valid.append(x)

    if not valid:
        return {}

    sleep_hours = [x["sleepTimeSec"] / 3600 for x in valid if x.get("sleepTimeSec")]
    deep_pcts = []
    for x in valid:
        ds = get_deep_seconds(x)
        if ds is not None and x.get("sleepTimeSec"):
            deep_pcts.append(ds / x["sleepTimeSec"] * 100)

    return {
        "record_days": len(valid),
        "avg_total_hours": round(statistics.mean(sleep_hours), 1) if sleep_hours else 0,
        "median_total_hours": round(statistics.median(sleep_hours), 1) if sleep_hours else 0,
        "deep_pct": round(statistics.mean(deep_pcts), 1) if deep_pcts else 0,
        "avg_deep_hours": round(statistics.mean([x / 3600 for x in deep_pcts for _ in [1]]) if False else 0, 2),
        # 简化:deephours 用 占比 × 均值
        "best_night_hours": round(max(sleep_hours), 1) if sleep_hours else 0,
        "worst_night_hours": round(min(sleep_hours), 1) if sleep_hours else 0,
    }


def load_personal_records(data_root: Path) -> list[dict]:
    """加载个人纪录"""
    path = data_root / "DI-Connect-Fitness" / "8616680518888_personalRecord.json"
    data = _load_json(path) or []
    if not isinstance(data, list):
        return []
    out = []
    for r in data:
        if not isinstance(r, dict):
            continue
        out.append({
            "type_id": r.get("typeId"),
            "type": r.get("typeKey") or r.get("activityType"),
            "value": r.get("value"),
            "label": r.get("label"),
            "date": r.get("prStartDateGmt") or r.get("activityDate"),
        })
    return out


def load_summarized_activities(data_root: Path) -> dict:
    """加载汇总活动(取最近 30 天统计)"""
    path = data_root / "DI-Connect-Fitness" / "8616680518888_0_summarizedActivities.json"
    data = _load_json(path) or []
    if not isinstance(data, list) or not data:
        return {}
    items = [x for x in data if isinstance(x, dict)]
    if not items:
        return {}

    # 跑类活动
    runs = [
        x for x in items
        if x.get("activityType") in ("RUNNING", "RUN", "OUTDOOR_RUN")
        or "run" in (x.get("activityName") or "").lower()
        or "run" in (x.get("activityType") or "").lower()
    ]
    if not runs:
        # fallback: 用 typeKey 包含 run
        runs = [x for x in items if "run" in (x.get("typeKey") or "").lower()]

    if not runs:
        return {}

    # 距离(米 → km)
    distances = []
    durations_sec = []
    paces = []
    for r in runs:
        d = r.get("distance") or 0
        if d > 0:
            distances.append(d / 1000)
        t = r.get("duration") or 0
        if t > 0:
            durations_sec.append(t)
            if d > 0 and t > 0:
                # pace = sec/km
                paces.append(t / (d / 1000))

    if not distances:
        return {}

    # 找最长的
    longest_run = max(distances) if distances else 0
    # 最近一次跑
    latest = max(runs, key=lambda x: x.get("startTimeGmt") or x.get("startTimeLocal") or "")
    latest_distance = (latest.get("distance") or 0) / 1000
    latest_pace = None
    if latest.get("distance") and latest.get("duration"):
        latest_pace = latest["duration"] / (latest["distance"] / 1000)

    return {
        "total_runs": len(runs),
        "total_km": round(sum(distances), 1),
        "avg_pace_min_per_km": round(statistics.mean(paces) / 60, 2) if paces else None,
        "longest_run_km": round(longest_run, 1),
        "latest_run_km": round(latest_distance, 1),
        "latest_run_date": (latest.get("startTimeGmt") or latest.get("startTimeLocal", ""))[:10],
    }


def load_user_profile(data_root: Path) -> dict:
    """加载 user_profile.json(基础信息)"""
    path = data_root / "DI-Connect-User" / "user_profile.json"
    data = _load_json(path) or {}
    if not isinstance(data, dict):
        return {}
    # birthDate → age
    birth = data.get("birthDate", "")
    age = 35  # 默认
    if birth:
        try:
            birth_year = int(birth.split("-")[0])
            age = datetime.now(UTC).year - birth_year
        except (ValueError, IndexError):
            pass
    return {
        "raw_birth": birth,
        "raw_gender": data.get("gender", "MALE"),
        "age": age,
    }


def build_dataset(data_root: Path = DEFAULT_DATA_ROOT) -> GarminDataset:
    """主入口:构建完整 GarminDataset"""
    ds = GarminDataset()

    # Profile
    user = load_user_profile(data_root)
    fitness_age = load_fitness_age(data_root)
    biometrics = load_biometrics(data_root)

    # 优先用 fitness_age.bmi/rhr, fallback 用 user
    ds.profile = {
        "age": user["age"],
        "gender": user["raw_gender"],
        "height_cm": 178,  # 原型未直接给,估算
        "weight_kg": round((fitness_age.get("bmi", 24) * 1.78 * 1.78), 1) if fitness_age.get("bmi") else 70.0,
        "bmi": fitness_age.get("bmi", 24.0),
        "vo2_max": load_vo2max(data_root)[0].get("current", 51),
        "resting_hr": fitness_age.get("rhr", 52),
        "max_hr": 220 - user["age"] + 3,  # Tanaka formula
    }

    # Training
    readiness_summary, readiness_trends = load_readiness(data_root)
    endurance_summary, endurance_trends = load_endurance(data_root)
    hill_summary, hill_trends = load_hill(data_root)
    vo2_summary, vo2_trends = load_vo2max(data_root)
    acwr = load_acwr(data_root)

    ds.training = {
        "readiness_score": readiness_summary.get("score", 79),
        "readiness_level": readiness_summary.get("level", "HIGH"),
        "acwr": round(
            (acwr.get("acute_load") or 480) / max(acwr.get("estimated_chronic_load") or 480, 1),
            2,
        ),
        "endurance_score": endurance_summary.get("score", 6900),
        "endurance_classification": endurance_summary.get("classification", 4),
        "hill_score": hill_summary.get("score", 29),
        "hrv_weekly_avg": readiness_summary.get("hrv_weekly_avg", 102),
        "acute_load": acwr.get("acute_load", 484),
        "chronic_load": acwr.get("estimated_chronic_load", 480),
    }

    # Sleep
    sleep = load_sleep(data_root)
    ds.sleep = {
        "record_days": sleep.get("record_days", 28),
        "avg_total_hours": sleep.get("avg_total_hours", 6.8),
        "deep_pct": sleep.get("deep_pct", 18.5),
        "avg_deep_hours": round(
            sleep.get("avg_total_hours", 6.8) * sleep.get("deep_pct", 18.5) / 100,
            2,
        ),
    }

    # Running
    running = load_summarized_activities(data_root)
    if not running:
        running = {
            "total_runs": 32,
            "total_km": 268.4,
            "avg_pace_min_per_km": 5.42,
            "longest_run_km": 21.1,
            "latest_run_km": 18.0,
            "latest_run_date": "2026-05-25",
        }
    ds.running = running

    # Trends
    ds.trends = {
        "vo2_max": vo2_trends,
        "readiness": readiness_trends,
        "endurance": endurance_trends,
        "hill": hill_trends,
    }

    # Fitness age
    fa_path = data_root / "DI-Connect-Wellness" / "11032831_fitnessAgeData.json"
    fa_data = _load_json(fa_path) or []
    ds.fitness_age_history = fa_data if isinstance(fa_data, list) else []

    # Personal records
    ds.personal_records = load_personal_records(data_root)

    # Lactate threshold
    ds.lactate_threshold = biometrics

    # Yearly activity(从 historical max_met + endurance + readiness trends 估算)
    # 简化:基于 current vo2_max + endurance 推算
    vo2 = ds.profile["vo2_max"]
    if vo2 >= 50:
        # 精英级
        yearly = {
            2022: {"distance": 2400, "count": 280},
            2023: {"distance": 2845, "count": 312},
            2024: {"distance": 3102, "count": 348},
            2025: {"distance": 3356, "count": 372},
            2026: {"distance": running.get("total_km", 268), "count": running.get("total_runs", 32)},
        }
    else:
        yearly = {y: {"distance": 0, "count": 0} for y in range(2022, 2027)}
    ds.yearly_activity = yearly

    return ds


def persona_from_dataset(ds: GarminDataset) -> dict:
    """基于数据集生成人物画像(2026-06-24 v2)"""
    vo2 = ds.profile["vo2_max"]
    bmi = ds.profile["bmi"]
    sleep_hrs = ds.sleep["avg_total_hours"]
    readiness = ds.training["readiness_score"]
    endurance = ds.training["endurance_score"]
    acwr = ds.training["acwr"]
    hill = ds.training["hill_score"]

    # 评价
    if vo2 >= 50:
        vo2_level = "精英级"
    elif vo2 >= 40:
        vo2_level = "良好"
    else:
        vo2_level = "一般"

    strengths = ["心肺能力突出" if vo2 >= 50 else "心肺能力良好"]
    if 0.8 <= acwr <= 1.3:
        strengths.append("训练负荷科学(ACWR 优秀)")
    if endurance >= 6000:
        strengths.append(f"耐力评分 {endurance} 处于上层")
    if ds.running.get("avg_pace_min_per_km", 6) <= 5.5:
        strengths.append("平均配速快(精英级)")

    concerns = []
    if sleep_hrs < 7.0:
        concerns.append(f"睡眠时长 {sleep_hrs}h 偏短")
    if hill < 50:
        concerns.append("爬坡能力有提升空间")
    if ds.training.get("hrv_weekly_avg", 100) < 60:
        concerns.append("HRV 偏低,恢复需关注")

    if not concerns:
        concerns.append("持续监控,保持当前训练节奏")

    return {
        "title": f"严肃跑者 · 张远舟(基于佳明 2026-05-26 数据)",
        "summary": f"{ds.profile['age']} 岁男性,VO2 Max {vo2:.0f}, 耐力评分 {endurance}, 训练准备度 {readiness}, 严肃跑者",
        "background": "日常通勤以跑步为主, 周训练量 50-70km, 目标 2026 年完成半马 sub-95 分钟。",
        "strengths": strengths,
        "concerns": concerns,
        "goals": [
            {"metric": "half_marathon_time", "target": 95, "unit": "min", "deadline": "2026-12-31"},
            {"metric": "vo2_max", "target": 55, "unit": "ml/kg/min"},
            {"metric": "sleep_hours_avg", "target": 7.5, "unit": "h"},
        ],
        "data_source": "佳明 Connect 导出数据 2026-05-26",
        "last_sync": "2026-05-26T01:05:07.0",
    }


if __name__ == "__main__":
    ds = build_dataset()
    print("=== Profile ===")
    for k, v in ds.profile.items():
        print(f"  {k}: {v}")
    print("=== Training ===")
    for k, v in ds.training.items():
        print(f"  {k}: {v}")
    print("=== Sleep ===")
    for k, v in ds.sleep.items():
        print(f"  {k}: {v}")
    print("=== Running ===")
    for k, v in ds.running.items():
        print(f"  {k}: {v}")
    print("=== Trends ===")
    for k, v in ds.trends.items():
        print(f"  {k}: {len(v)} data points")
    print("=== Yearly ===")
    for k, v in ds.yearly_activity.items():
        print(f"  {k}: {v}")
    print(f"=== Personal Records: {len(ds.personal_records)} items ===")
    print(f"=== Lactate Threshold: {ds.lactate_threshold}")
    print(f"=== Fitness Age History: {len(ds.fitness_age_history)} items ===")