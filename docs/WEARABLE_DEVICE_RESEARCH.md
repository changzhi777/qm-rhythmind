# 可穿戴设备数据接入研究（Phase 3.5）

> 版本：0.1.8
> 状态：研究文档（供决策参考）

---

## 1. 概述

RHYTHMIND 律动需要从用户可穿戴设备（手表/手环）摄取：
- 心率（Heart Rate）
- 步数（Steps）
- 睡眠数据（Sleep）
- 血压（Blood Pressure）
- 血氧（SpO2）

平台覆盖：iOS（Apple Watch）+ Android（WearOS/Garmin/Fitbit）

---

## 2. 主流方案对比

| 方案 | 平台 | 认证方式 | 数据覆盖 | 接入难度 | 隐私模式 |
|------|------|---------|---------|---------|---------|
| Apple HealthKit | iOS | OAuth 2.0（Health app 授权） | HR/Steps/Sleep/HRV/SpO2 | 高（需 native app） | 可离线 |
| Google Health Connect | Android | OAuth 2.0 + permissions | HR/Steps/Sleep/BP/SpO2 | 高（需 Play Services） | 可离线 |
| Fitbit Web API | 跨平台 | OAuth 2.0 | HR/Steps/Sleep/Weight | 中（需 Fitbit 账号） | 云端 |
| Garmin Connect API | Garmin 设备 | OAuth 2.0 | HR/Steps/Sleep/HRV | 高（企业账号限制） | 云端 |
| Web Bluetooth | 浏览器 | BLE 直连 | 取决于设备 | 低（设备碎片化严重） | 本地 |
| 手动 CSV 上传 | 全部 | 无 | 任意格式 | 最低 | 完全本地 |

---

## 3. iOS：Apple HealthKit

### 3.1 限制

Apple HealthKit **不能直接从服务器拉取数据**。工作流程：

```
用户 Apple Watch → Apple Health App（本地存储）
                        ↓
              用户主动授权给第三方 App
                        ↓
              iOS App 将数据通过 HTTP 提交到后端
```

**结论**：HealthKit 数据无法被服务器直接拉取，必须通过：
1. **Native iOS App** 中间层（用户授权后，App 转发数据到 API）
2. 或 **Shortcuts App** + API 调用（用户自动化）
3. 或 **Web Bluetooth**（仅支持部分心率带）

### 3.2 推荐集成路径

```
iOS App（Swift/SwiftUI）
    │
    ├─ HKHealthStore.requestAuthorization([.heartRate, .stepCount, .sleepAnalysis])
    ├─ HKStatisticsQuery / HKAnchoredObjectQuery 读取数据
    └─ POST /api/v1/health/ingest 转发到后端
```

### 3.3 数据类型

| HKQuantityType | 单位 | 采样频率 |
|----------------|------|---------|
| heartRate | count/min (bpm) | 持续 |
| stepCount | count | 汇总 |
| sleepAnalysis | category（asleep/awake） | 每段 |
| oxygenSaturation | % | 按需 |
| bloodPressureSystolic | mmHg | 按需 |

---

## 4. Android：Google Health Connect

### 4.1 限制

同 HealthKit，Health Connect **不在服务器端存储数据**，工作流程类似：

```
用户 WearOS 设备 → Health Connect App（本地）
                        ↓
              用户授权给第三方 App
                        ↓
              App 通过 Health Connect API 读取 → POST 到后端
```

### 4.2 推荐集成路径

```kotlin
// Android (Kotlin)
val permissions = setOf(
    ReadPermission(DataType.HEART_RATE_SAMPLES),
    ReadPermission(DataType.STEPS_TOTAL),
    ReadPermission(DataType.SLEEP_STAGES),
    ReadPermission(DataType.BLOOD_GLUCOSE)
)

// 调用 Health Connect API 读取后 POST 到 /api/v1/health/ingest
```

### 4.3 与 iOS 共同点

两者都需要**客户端 App 作为数据管道**，服务器无法主动拉取。

---

## 5. 跨平台替代方案

### 5.1 Fitbit Web API（OAuth 2.0）

**优点**：账号体系完整，数据种类丰富，服务器端可主动轮询  
**缺点**：需要用户授权 Fitbit 账号，中国区服务不稳定

```
GET https://api.fitbit.com/1/user/-/activities/heart/date/today/1d.json
Authorization: Bearer <access_token>

Response:
{
  "activities-heart": [{
    "date": "2026-05-12",
    "value": {"zones": {"outOfRange": {...}}}
  }]
}
```

**可行方案**：后端定时轮询 Fitbit API（需用户 OAuth token 存储）

### 5.2 手动 CSV 上传（最可靠兜底）

用户从 Apple Health / Google Health 导出 CSV，手动上传到 Dashboard。

```
POST /api/v1/health/ingest
Content-Type: multipart/form-data

file: <CSV file>
source: "apple_health_export" | "google_health_export" | "fitbit_export"
```

CSV 格式标准化：
```csv
timestamp,heart_rate,steps,sleep_minutes,spo2
2026-05-12T08:00:00Z,65,1200,0,98
2026-05-12T08:30:00Z,72,300,0,97
```

---

## 6. 推荐实施策略（按优先级）

### P0 — 最小可行产品（MVP）

**手动 CSV 上传**

理由：
- 无需第三方 OAuth
- 服务器直接接收，无平台限制
- 用户有控制权（导出 → 审查 → 上传）
- 技术实现简单

```python
# POST /api/v1/health/ingest
from fastapi import File, UploadFile
from rhythmind.api.routers.health import router

@router.post("/ingest", summary="接收可穿戴设备导出数据")
async def ingest_wearable_data(
    file: UploadFile = File(...),
    source: str = "manual",  # apple_health / google_health / fitbit / manual
):
    # CSV 解析 + 数据标准化 + 存入 InfluxDB
    ...
```

### P1 — 跨平台同步（Phase 2+）

**Fitbit OAuth 轮询**（欧美用户为主）
- 用户授权后，后端每天定时拉取数据
- Token 自动刷新

**iOS Shortcuts + API**（无需自建 App）
- 用户通过 iOS Shortcuts App 自动化：
  - 每天固定时间读取 Apple Health 数据
  - 通过 HTTP Action 调用 `POST /api/v1/health/ingest`
- 无需开发原生 App，但依赖用户配置

### P2 — 原生 App（长期）

- iOS：SwiftUI + HealthKit → `POST /api/v1/health/ingest`
- Android：Kotlin + Health Connect → `POST /api/v1/health/ingest`
- 一次性开发，长期收益

---

## 7. 数据标准化

无论数据来源（Apple Health / Google Health / Fitbit / CSV），统一转换为：

```python
@dataclass
class WearableReading:
    user_id: str
    timestamp: datetime
    heart_rate: int | None           # bpm
    steps: int | None
    sleep_minutes: int | None
    spo2: float | None               # %
    blood_pressure_systolic: int | None  # mmHg
    blood_pressure_diastolic: int | None # mmHg
    source: str                      # "apple_health" / "google_health" / "fitbit" / "manual"
```

存储到 InfluxDB：
```
measurement: wearable_readings
tags: user_id, source, device_type
fields: heart_rate, steps, sleep_minutes, spo2, bp_systolic, bp_diastolic
```

---

## 8. 隐私考量

| 原则 | 实现 |
|------|------|
| 数据最小化 | 仅请求必要权限（HR + Steps，不请求位置） |
| 本地处理优先 | iOS/Android 数据不经过第三方服务器中转 |
| 脱敏存储 | 原始数据入 InfluxDB，分析结果入 AgentMemory |
| 用户控制 | 用户可随时通过 `/privacy/delete` 清除数据 |
| 知情同意 | 首次上传前展示隐私声明 |

---

## 9. 实现优先级建议

| 阶段 | 功能 | 工作量 | 价值 |
|------|------|--------|------|
| Phase 3.5（当前） | CSV 上传端点 | 1 人日 | P0 |
| Phase 2.1 | Fitbit OAuth 轮询 | 3 人日 | P1（欧美用户） |
| Phase 2.2 | iOS Shortcuts 集成文档 | 0.5 人日 | P1（无需开发 App） |
| Phase 3 | Native iOS App（HealthKit） | 2 周 | P2 |
| Phase 3 | Native Android App（Health Connect） | 2 周 | P2 |

---

## 10. 结论

**最简单可行方案**：CSV 上传端点 + iOS Shortcuts 自动化

- 无需 OAuth 或第三方集成
- 用户导出 Apple Health → Shortcuts → POST 到 API
- 覆盖 iOS 生态中最有意愿同步数据的用户群体
- Android 用户可使用手动 CSV 或等待 Phase 2 Fitbit 集成

> **下一步**：在 `src/rhythmind/api/routers/health.py` 中实现 `/ingest` 端点，支持 CSV 文件上传和数据标准化。