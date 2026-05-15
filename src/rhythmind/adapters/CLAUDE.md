# rhythmind/adapters — 模型适配层

> `[根目录(../../CLAUDE.md) > **rhythmind** > **adapters**`

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

## 变更记录 (Changelog)

- **2026-05-13** 移除 OllamaAdapter，新增 OMLXAdapter（oMLX 本地模型服务）
- **2026-05-12** 完整扫描完成，新增文件清单和 InfluxDB Schema
- **2026-05-12** 首次 AI 上下文初始化