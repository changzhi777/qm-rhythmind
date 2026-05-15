# rhythmind/ingestion — 数据入库引擎

> 📍 [Ag2Hermes](../../../../CLAUDE.md) > [qm-rhythmind](../../../CLAUDE.md) > **ingestion**

---

## 模块职责

数据源适配 + 入库引擎。负责从外部数据源（Garmin Connect 等）读取原始数据，转换为统一数据模型，写入 HealthFact 知识图谱，并可选触发 AI 分析报告生成。

**设计模式**：适配器模式 — `BaseDataSourceAdapter` 抽象基类解耦数据读取与业务逻辑。

---

## 入口与启动

```python
from rhythmind.ingestion import GarminDataSourceAdapter, IngestionEngine

adapter = GarminDataSourceAdapter(data_dir="path/to/garmin_export")
engine = IngestionEngine(adapter, user_id="garmin_user_001")
result = await engine.ingest()    # 数据入库
report = await engine.analyze()   # AI 分析报告
```

**脚本入口**：
- `scripts/run_ingestion.py` — 一键入库 + 分析
- `scripts/ingest_garmin_export.py` — Garmin 数据导入专用

---

## 对外接口

### IngestionEngine

| 方法 | 返回 | 说明 |
|------|------|------|
| `ingest()` | `IngestionResult` | 完整入库流程（profile/activities/sleep/body/training/events） |
| `analyze()` | `str` | 调用本地模型生成 AI 分析报告 |
| `get_dashboard_data()` | `dict` | 获取仪表盘所需数据 |
| `get_reports(limit)` | `list[dict]` | 获取历史 AI 报告列表 |

### BaseDataSourceAdapter (ABC)

| 抽象方法 | 返回 | 说明 |
|---------|------|------|
| `source_name` | `str` | 数据源标识（如 'garmin'） |
| `load_profile()` | `UserProfile` | 用户基本信息 |
| `load_activities()` | `list[Activity]` | 运动活动列表 |
| `load_sleep()` | `list[SleepRecord]` | 睡眠记录 |
| `load_body_metrics()` | `list[BodyMetric]` | VO2Max/HRV/心率时序 |
| `load_training_metrics()` | `TrainingMetrics` | 训练指标 |
| `load_health_events()` | `list[HealthEvent]` | 健康告警事件 |

### 数据模型

| 模型 | 关键字段 |
|------|---------|
| `UserProfile` | gender, height_cm, weight_kg, bmi, vo2_max, resting_hr, max_hr, hr_zones |
| `Activity` | date, activity_type, distance_meters, duration_seconds, avg_hr, pace_min_per_km |
| `SleepRecord` | total_hours, deep_hours, rem_hours, deep_pct |
| `BodyMetric` | vo2_max, fitness_age, hrv, resting_hr, weight_kg |
| `TrainingMetrics` | endurance_score, acwr, acute_load, chronic_load, race_predictions |
| `HealthEvent` | event_type, value, threshold |
| `IngestionResult` | 各类 records 计数 + errors 列表 |

---

## 关键依赖与配置

- **FactManager**: `rhythmind.core.memory.fact_manager` — 写入 HealthFact
- **AdapterRouter**: `rhythmind.adapters.adapter_router` — 调用 LLM 生成报告
- **OMLXAdapter**: 直接实例化长超时适配器（报告生成耗时长）
- **默认模型**: `omlX://gemma-4-e4b-it-4bit`

---

## 常见问题 (FAQ)

**Q: 如何添加新数据源？**
A: 继承 `BaseDataSourceAdapter`，实现所有抽象方法，然后传给 `IngestionEngine`。

**Q: analyze() 使用什么模型？**
A: 默认 `omlX://gemma-4-e4b-it-4bit`，可通过 `model_spec` 参数覆盖。

---

## 相关文件清单

```
src/rhythmind/ingestion/
├── __init__.py              # 公开 API
├── base.py                  # ABC 基类 + 数据模型 (dataclass)
├── engine.py                # IngestionEngine 入库 + 分析
└── garmin_adapter.py        # Garmin Connect 导出适配器
```

---

## 变更记录 (Changelog)

- **2026-05-15** 首次 AI 上下文初始化
