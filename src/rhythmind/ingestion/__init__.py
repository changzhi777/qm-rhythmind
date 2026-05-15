"""
ingestion — 数据源适配器 + 入库引擎

公开 API:
  - BaseDataSourceAdapter  — 适配器抽象基类
  - GarminDataSourceAdapter — Garmin Connect 数据适配器
  - IngestionEngine         — 入库 + AI 分析引擎
"""
from rhythmind.ingestion.base import (
    Activity,
    BaseDataSourceAdapter,
    BodyMetric,
    HealthEvent,
    IngestionResult,
    SleepRecord,
    TrainingMetrics,
    UserProfile,
)
from rhythmind.ingestion.engine import IngestionEngine
from rhythmind.ingestion.garmin_adapter import GarminDataSourceAdapter

__all__ = [
    "BaseDataSourceAdapter",
    "GarminDataSourceAdapter",
    "IngestionEngine",
    "UserProfile",
    "Activity",
    "SleepRecord",
    "BodyMetric",
    "TrainingMetrics",
    "HealthEvent",
    "IngestionResult",
]
