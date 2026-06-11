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

## 数据流

```
Garmin Connect 导出包 (.zip 解压)
    │
    ├── DI_CONNECT/  ─→ 用户档案 (Profile.csv)
    ├── DI_ACTIVITY/ ─→ 运动活动 (Activities.csv)
    ├── DI_SLEEP/    ─→ 睡眠记录 (SleepData.csv)
    ├── DI_BIOMETRICS/ ─→ 身体指标 (VO2Max.csv, HRV.csv, RHR.csv)
    └── DI_TRAINING/ ─→ 训练指标 (TrainingStatus.csv, RacePredictor.csv)
         │
         ▼
GarminDataSourceAdapter
    ├── validate() ─→ 检查 11 个子目录完整性
    ├── load_profile() ─→ UserProfile (gender, height, weight, BMI, vo2_max, hr_zones)
    ├── load_activities() ─→ list[Activity] (type, distance, duration, avg_hr, pace)
    ├── load_sleep() ─→ list[SleepRecord] (total/deep/rem/light/awake hours)
    ├── load_body_metrics() ─→ list[BodyMetric] (vo2_max trend, HRV, resting_hr, fitness_age)
    ├── load_training_metrics() ─→ TrainingMetrics (ACWR, acute_load, endurance, race predictions)
    └── load_health_events() ─→ list[HealthEvent] (abnormal HR alerts)
         │
         ▼
IngestionEngine
    ├── ingest()  ─→ 6 阶段流水线写入 HealthFact
    │   ├── 1. profile       → 9 个 fact (gender/height/weight/bmi/age/vo2max/rhr/mhr/zones)
    │   ├── 2. activities    → 3 个 fact (total_count/yearly stats/running summary)
    │   ├── 3. sleep         → 1 个 fact (avg_total/deep/rem/deep_pct over all records)
    │   ├── 4. body_metrics  → 1 个 fact (vo2max_latest/max, hrv_avg/max, rhr_avg, fitness_age)
    │   ├── 5. training      → 1 个 fact (endurance/hill/acwr/readiness/race_predictions)
    │   └── 6. health_events → 1 个 fact (count + threshold + recent 5 events)
    │
    ├── analyze() ─→ 调用 omlX://gemma-4-e4b-it-4bit 生成 AI 报告
    │   └── system prompt 含 6 段报告结构模板（总体评价→建议，800-1200字）
    │
    └── get_dashboard_data() / get_reports() ─→ 查询已入库数据
```

### 错误处理矩阵

| 阶段 | 异常处理 | 影响 |
|------|---------|------|
| profile 失败 | `result.errors.append()`，继续下一阶段 | 缺失基础生理数据 |
| activities 失败 | 同上 | 无运动统计 |
| sleep 失败 | 同上 | 无睡眠分析 |
| body_metrics 失败 | 同上 | 无 VO2Max/HRV 趋势 |
| training 失败 | 同上 | 无 ACWR/训练负荷 |
| health_events 失败 | 同上 | 无异常告警 |
| analyze() 无数据 | 返回 "无可用数据，请先执行入库" | 无报告 |

每阶段独立 try/except，任一失败不阻断后续阶段（best-effort 入库）。

### GarminDataSourceAdapter 数据目录结构

| Garmin 子目录 | 关键 CSV | 提取字段数 |
|--------------|---------|-----------|
| `DI_CONNECT/` | Profile.csv | 5 (gender, birth_date, height, weight, vo2max) |
| `DI_ACTIVITY/` | Activities.csv | 14 (date, type, name, duration, distance, avg_hr, ...) |
| `DI_SLEEP/` | SleepData.csv | 5 (date, total/deep/light/rem/awake hours) |
| `DI_BIOMETRICS/` | VO2Max.csv, HRV.csv, RHR.csv | 5 (date, vo2max, fitness_age, hrv, resting_hr) |
| `DI_TRAINING/` | TrainingStatus.csv, RacePredictor.csv | 8+3 (endurance, hill, acute_load, race_preds) |

### IngestionResult 字段

```python
@dataclass
class IngestionResult:
    profile_records: int = 0       # profile fact 条数（正常 9）
    activity_records: int = 0      # activity fact 条数（正常 3）
    sleep_records: int = 0         # sleep fact 条数（正常 1）
    body_metric_records: int = 0   # body_metric fact 条数（正常 1）
    training_records: int = 0      # training fact 条数（正常 1）
    health_event_records: int = 0  # health_event fact 条数（正常 0-1）
    errors: list[str]              # 各阶段错误信息
    # total → sum of all *_records
```

### Activity 计算属性

| 属性 | 公式 | 用途 |
|------|------|------|
| `pace_min_per_km` | (duration_sec/60) / (distance_m/1000) | 跑步配速 |
| `distance_km` | distance_meters / 1000 | 距离（公里） |
| `bmi` (UserProfile) | weight_kg / (height_cm/100)² | BMI 指数 |
| `deep_pct` (SleepRecord) | deep_hours / total_hours × 100 | 深睡占比 |
| `age` (UserProfile) | (now - birth_date).days // 365 | 年龄 |

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充数据流图、错误处理矩阵、Garmin 目录结构、IngestionResult/Activity 完整字段、计算属性表
- **2026-05-15** 首次 AI 上下文初始化
