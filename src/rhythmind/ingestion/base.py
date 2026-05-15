"""
ingestion/base.py — 数据源适配器抽象基类 + 数据模型

采用适配器模式，解耦数据读取与业务逻辑。
新增数据源只需实现 BaseDataSourceAdapter，IngestionEngine 不做任何修改。

已规划适配器：
  - GarminDataSourceAdapter  — Garmin Connect 导出包
  - (Future) AppleHealthAdapter
  - (Future) StravaAdapter
  - (Future) FitbitAdapter
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── 数据模型（适配器输出统一格式）────────────────────────────────────────────

@dataclass
class UserProfile:
    gender: str
    birth_date: str
    height_cm: float
    weight_kg: float
    vo2_max: float | None = None
    lactate_threshold_hr: float | None = None
    ftp_watts: float | None = None
    resting_hr: int | None = None
    max_hr: int | None = None
    hr_zones: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def bmi(self) -> float:
        return self.weight_kg / (self.height_cm / 100) ** 2

    @property
    def age(self) -> int:
        birth = datetime.strptime(self.birth_date, "%Y-%m-%d")
        return (datetime.now() - birth).days // 365


@dataclass
class Activity:
    date: datetime
    activity_type: str
    name: str
    duration_seconds: float
    distance_meters: float
    avg_hr: float | None = None
    max_hr: float | None = None
    calories: float | None = None
    elevation_gain_m: float | None = None
    avg_cadence: float | None = None
    steps: float | None = None
    avg_speed_ms: float | None = None
    avg_power: float | None = None
    aerobic_te: float | None = None
    location: str | None = None

    @property
    def pace_min_per_km(self) -> float | None:
        if self.distance_meters > 0:
            return (self.duration_seconds / 60) / (self.distance_meters / 1000)
        return None

    @property
    def distance_km(self) -> float:
        return self.distance_meters / 1000


@dataclass
class SleepRecord:
    date: str
    total_hours: float
    deep_hours: float
    light_hours: float
    rem_hours: float
    awake_hours: float = 0.0

    @property
    def deep_pct(self) -> float:
        return self.deep_hours / self.total_hours * 100 if self.total_hours > 0 else 0


@dataclass
class BodyMetric:
    date: str
    vo2_max: float | None = None
    fitness_age: float | None = None
    hrv: float | None = None
    resting_hr: float | None = None
    weight_kg: float | None = None


@dataclass
class TrainingMetrics:
    endurance_score: float | None = None
    endurance_classification: str | None = None
    hill_score: float | None = None
    acute_load: float | None = None
    chronic_load: float | None = None
    acwr: float | None = None
    acwr_status: str | None = None
    training_readiness_score: float | None = None
    training_readiness_level: str | None = None
    race_predictions: dict[str, int] = field(default_factory=dict)


@dataclass
class HealthEvent:
    date: str
    event_type: str
    value: float
    threshold: float
    description: str = ""


@dataclass
class IngestionResult:
    profile_records: int = 0
    activity_records: int = 0
    sleep_records: int = 0
    body_metric_records: int = 0
    training_records: int = 0
    health_event_records: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.profile_records
            + self.activity_records
            + self.sleep_records
            + self.body_metric_records
            + self.training_records
            + self.health_event_records
        )


# ── 适配器抽象基类 ─────────────────────────────────────────────────────────

class BaseDataSourceAdapter(ABC):
    """
    数据源适配器抽象基类。

    每个适配器负责从特定数据源读取原始数据，
    转换为统一的数据模型输出，供 IngestionEngine 使用。
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """数据源标识，如 'garmin'、'apple_health'、'strava'"""

    @abstractmethod
    def load_profile(self) -> UserProfile:
        """加载用户基本信息。"""

    @abstractmethod
    def load_activities(self) -> list[Activity]:
        """加载运动活动列表。"""

    @abstractmethod
    def load_sleep(self) -> list[SleepRecord]:
        """加载睡眠记录。"""

    @abstractmethod
    def load_body_metrics(self) -> list[BodyMetric]:
        """加载身体指标（VO2Max/HRV/心率/体重）时序数据。"""

    @abstractmethod
    def load_training_metrics(self) -> TrainingMetrics:
        """加载最新训练指标。"""

    @abstractmethod
    def load_health_events(self) -> list[HealthEvent]:
        """加载健康告警事件（异常心率等）。"""

    def validate(self) -> list[str]:
        """验证数据源是否可读，返回错误列表（空=OK）。"""
        return []
