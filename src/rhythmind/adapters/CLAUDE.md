# rhythmind/adapters — 模型适配层

> `[根目录(../../CLAUDE.md) > **rhythmind** > **adapters**`

> **最后更新:** 2026-05-27T10:50:56+08:00

---

## 变更记录

- **2026-05-27** 新增 `omlX_compliance_base_url` 配置，合规审查可使用独立 oMLX 实例

---

## 模块职责

多模型适配层，统一封装 MLX（Apple Silicon 本地推理）、oMLX（HTTP 本地服务）、LiteLLM（云端网关）三种推理后端，对外暴露统一的 `chat()` 接口。

**路由规范**：
- `mlx://<hf_repo>` → `MLXAdapter`
- `omlX://<model_name>` → `OMLXAdapter`
- 其他字符串 → `LiteLLMAdapter`

---

## 入口与启动

- **单例入口**: `from rhythmind.adapters import adapter_router`
- **配置来源**: `rhythmind.config.settings.model_primary_spec` / `model_compliance_spec`
- **初始化时机**: 模块首次 import 时自动初始化单例

---

## 对外接口

### ModelAdapter (ABC)

```python
class ModelAdapter(ABC):
    async def chat(self, messages: list[dict], **kwargs) -> str: ...
    async def health_check(self) -> bool: ...
```

### AdapterRouter

```python
class AdapterRouter:
    def chat(self, model_spec: str, messages: list[dict], **kwargs) -> str: ...
    def route(self, model_spec: str) -> ModelAdapter: ...
    def get(self, model_spec: str) -> ModelAdapter: ...
    def clear_cache(self) -> None: ...
```

### 具体实现

| 类 | 后端 | 关键参数 |
|---|---|---|
| `MLXAdapter` | Apple MLX (asyncio.to_thread) | `mlx_thinking_mode`, `mlx_max_tokens`, `mlx_temperature`, `semaphore_limit=1` |
| `OMLXAdapter` | oMLX HTTP | `base_url`, `api_key`, health check `/v1/models` |
| `LiteLLMAdapter` | LiteLLM Proxy | `litellm_base_url`, `litellm_master_key` |

### InfluxDB 客户端

```python
class InfluxClient:
    async def write_metrics(self, point: MetricPoint) -> bool: ...
    async def query_range(self, user_id, fields, start, stop, aggregation_window, fn) -> dict[str, TrendSeries]: ...
    async def query_latest(self, user_id, fields) -> dict[str, float]: ...
    async def close(self) -> None: ...

class MetricPoint:
    user_id: str
    source: str
    sport_type: str = "general"
    fields: dict[str, float | int]
    ts: datetime | None
```

---

## 关键依赖与配置

- **MLX**: `mlx_lm` 包，Apple Silicon 专用
- **oMLX**: `openai.AsyncOpenAI`，health check 通过 `/v1/models`
- **LiteLLM**: `litellm` 包，透传 model_spec 作为 litellm model name
- **InfluxDB**: `influxdb-client[async]`

配置项（`rhythmind.config.Settings`）:
- `model_primary_spec`, `model_compliance_spec`
- `mlx_thinking_mode`, `mlx_max_tokens`, `mlx_temperature`, `mlx_semaphore_limit`
- `omlX_base_url`, `omlX_api_key`
- `litellm_url`, `litellm_master_key`
- `influxdb_url`, `influxdb_token`, `influxdb_org`, `influxdb_bucket`

---

## 数据模型

无持久化数据模型，仅内存状态。

**InfluxDB Schema**:
- measurement: `health_metrics`
- tags: `user_id`, `source`, `sport_type`
- fields: `heart_rate_avg`, `heart_rate_max`, `steps`, `distance_km`, `calories`, `sleep_hours`, `hrv`, `body_fat_pct`, `muscle_mass_kg`, `water_pct`, `visceral_fat`
- timestamp: UTC, nanosecond precision

---

## 测试与质量

- 测试文件：`tests/unit/test_model_adapters.py` (~22K 行，覆盖全部 3 种 adapter)
- 代码风格：`ruff check src/rhythmind/adapters/`
- 健康检查失败时 adapter_router 自动 fallback 到下一个可用适配器

---

## 常见问题 (FAQ)

**Q: MLX 推理 OOM 怎么办？**
A: `MLXAdapter` 内部使用 `Semaphore(mlx_semaphore_limit)` 限制并发数为 1，避免 M4 16GB 内存溢出。

**Q: oMLX 服务不可用时是否自动降级？**
A: 由 `AdapterRouter` 层面处理降级，需要在上层（`HealthRouter` / `HermesBase`）捕获异常后切换。

**Q: InfluxDB 不可用会影响主流程吗？**
A: `InfluxClient` 写失败时静默降级，不阻断健康检查流程。

---

## 相关文件清单

```
src/rhythmind/adapters/
├── __init__.py              # 公开 API: InfluxClient, ModelAdapter, *Adapter, AdapterRouter
├── adapter_router.py        # 单例 + 前缀路由分发
├── model_adapter.py         # ABC 基类
├── mlx_adapter.py           # Apple MLX 推理 (Qwen3 thinking 模式)
├── omlX_adapter.py          # oMLX 本地模型服务客户端 (OpenAI 兼容)
├── litellm_adapter.py       # LiteLLM Proxy 客户端
└── influx_client.py         # InfluxDB 2.x 异步客户端 (Flux 查询)
```

---

## 模型路由流程

```
adapter_router.chat(model_spec="omlX://gemma-4-e4b-it-4bit", messages=[...])
    │
    ├─ model_spec.startswith("mlx://")    ─→ MLXAdapter(model_name, semaphore=1)
    │   └─ asyncio.to_thread(mlx_lm.generate, prompt)  # Apple Silicon 本地
    │
    ├─ model_spec.startswith("omlX://")   ─→ OMLXAdapter(model_name, base_url=...)
    │   └─ openai.AsyncOpenAI.chat.completions.create   # HTTP OpenAI 兼容
    │
    └─ 其他字符串                          ─→ LiteLLMAdapter(model_spec)
        └─ litellm.acompletion(model=model_spec)         # LiteLLM Proxy
```

### 适配器对比

| 特性 | MLXAdapter | OMLXAdapter | LiteLLMAdapter |
|------|-----------|-------------|----------------|
| 运行位置 | 本地 Apple Silicon | 本地 HTTP 服务 | 云端网关 |
| 并发控制 | `Semaphore(1)` | 无限制 | 无限制 |
| 超时 | 默认 60s | 默认 60s (可覆盖) | LiteLLM 默认 |
| thinking_mode | ✅ (Qwen3) | ❌ | ❌ |
| 健康检查 | `mlx_lm` 可用性 | `/v1/models` | `/health` |
| 故障降级 | 抛异常 | 抛异常 | 抛异常 |
| 配置前缀 | `mlx_*` | `omlX_*` | `litellm_*` |

### OMLXAdapter 合规审查独立 URL

```python
# 普通推理
OMLXAdapter("gemma-4-e4b-it-4bit", base_url=settings.omlX_base_url)

# 合规审查可指定独立实例
OMLXAdapter("gemma-4-e4b-it-4bit", base_url=settings.omlX_compliance_base_url)
# 用途：合规模型运行在独立容器/GPU，避免与业务推理争抢资源
```

## InfluxDB 查询模式

### query_range — 时序范围查询

```python
data = await influx.query_range(
    user_id="alice",
    fields=["heart_rate_avg", "steps", "sleep_hours"],
    start="-7d",
    stop="now()",
    aggregation_window="1h",
    fn="mean",
)
# → {
#     "heart_rate_avg": TrendSeries(
#         label="heart_rate_avg",
#         values=[72.3, 74.1, ...],      # 按 aggregation_window 聚合
#         timestamps=["2026-06-04T00:00:00Z", ...]
#     ),
#     ...
# }
```

### query_latest — 最新值查询

```python
latest = await influx.query_latest(
    user_id="alice",
    fields=["vo2max", "hrv", "resting_hr"],
)
# → {"vo2max": 48.5, "hrv": 52.0, "resting_hr": 58}
```

### MetricPoint 写入

```python
point = MetricPoint(
    user_id="alice",
    source="garmin_connect",
    sport_type="running",
    fields={"heart_rate_avg": 142, "steps": 12500, "calories": 450},
    ts=datetime.now(tz=UTC),
)
await influx.write_metrics(point)
```

### InfluxDB 降级策略

| 操作 | 失败行为 |
|------|---------|
| `write_metrics()` | 静默降级，不抛异常 |
| `query_range()` | 返回空 dict `{}` |
| `query_latest()` | 返回空 dict `{}` |
| `delete_user_data()` | 抛出 `NotImplementedError`（未实现时） |

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充模型路由流程图、三适配器对比表（并发/超时/降级）、OMLXAdapter 合规独立 URL、InfluxDB query_range/query_latest/MetricPoint 完整签名、降级策略矩阵
- **2026-05-13** 移除 OllamaAdapter，新增 OMLXAdapter（oMLX 本地模型服务）
- **2026-05-12** 完整扫描完成，新增文件清单和 InfluxDB Schema
- **2026-05-12** 首次 AI 上下文初始化