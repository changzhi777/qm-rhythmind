# rhythmind/observability — 可观测性

> `[根目录(../../CLAUDE.md) > **rhythmind** > **observability**`

---

## 模块职责

Prometheus 指标 + OpenTelemetry 追踪 + Sentry 错误追踪 + Langfuse LLM 观测。

---

## 入口与启动

- **指标安装**: `install_metrics(app)` — 注册 `/metrics` 端点 + 中间件
- **追踪安装**: `install_tracing(app, service_name)` — OTel FastAPI instrumentation
- **LLM 观测初始化**: `init_langfuse()` — 初始化 Langfuse 客户端（settings.langfuse_enabled）
- **调用时机**: `api/main.py` 应用创建后立即调用

---

## 对外接口

### install_metrics

```python
def install_metrics(app: FastAPI) -> None: ...
```

### install_tracing

```python
def install_tracing(app: FastAPI, service_name: str) -> None: ...
```

### init_langfuse

```python
def init_langfuse() -> bool: ...
```

### @observe_llm 装饰器

```python
@observe_llm(model="gpt-4o", agent="coach_agent")
async def my_llm_func(messages, ...) -> str: ...
```

自动采集 input/output/tokens/cost/latency 到 Langfuse。禁用时退化为 no-op。

### 指标名称

| 指标 | 类型 | 描述 |
|------|------|------|
| `HTTP_REQUESTS` | Counter | HTTP 请求计数 (labels: method, endpoint, status) |
| `HTTP_LATENCY` | Histogram | HTTP 请求延迟 (labels: method, endpoint) |
| `LLM_CALLS` | Counter | LLM 调用计数 (labels: adapter_kind, status) |
| `LLM_LATENCY` | Histogram | LLM 调用延迟 (labels: adapter_kind) |
| `COMPLIANCE_BLOCKS` | Counter | 合规拦截计数 (labels: gate) |
| `POOL_HIT` | Counter | Agent 池命中 |
| `POOL_MISS` | Counter | Agent 池未命中 |
| `LOOP_GUARD_CALLS` | Counter | LoopGuard 节流计数 (labels: intent, result) |

### 工具函数

```python
def record_pool_hit() -> None: ...
def record_pool_miss() -> None: ...
```

---

## LLM 观测模块

### 文件清单

| 文件 | 职责 |
|------|------|
| `llm_observe.py` | `init_langfuse()`, `get_langfuse()`, `@observe_llm` 装饰器, token/cost 估算 |
| `suggestion_engine.py` | `Suggestion`, `ModelMetrics` 数据类 + 5 条规则引擎 |

### 规则引擎（5 条规则）

| 规则 | 条件 | 严重级 |
|------|------|--------|
| 模型延迟偏高 | avg_latency > 2x 全局均值 | warn |
| Token 利用率低 | output/input < 5% | info |
| 错误率异常 | error_rate > 5% | critical |
| 成本周环比增长 | week_delta > 30% | warn |
| 重复 Prompt | repeated > 10/小时 | info |

### API 端点 (`api/routers/llm_observe.py`)

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/llm-observe/metrics` | GET | 汇总指标（直查 Langfuse PG） |
| `/api/v1/llm-observe/traces` | GET | Trace 列表（分页） |
| `/api/v1/llm-observe/traces/{id}` | GET | Trace 详情 |
| `/api/v1/llm-observe/suggestions` | GET | 规则引擎建议 |
| `/api/v1/llm-observe/analyze` | POST | LLM 深度分析报告 |

### Langfuse v2 表结构适配

SQL 查询使用 `observations` 表的 v2 列名：`level`（非 status）、`total_tokens`/`total_cost`（非 JSON）、`EXTRACT(EPOCH FROM (end_time - start_time))` 计算延迟。

---

## 关键依赖与配置

- **指标**: `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`
- **Sentry**: `sentry-sdk[fastapi]`
- **Langfuse**: `langfuse>=4.0,<5.0`
- **配置**: `settings.sentry_dsn`, `settings.langfuse_*`, `settings.env`, `settings.debug`

---

## 测试与质量

- 测试文件：`tests/unit/test_llm_observe.py`（17 个测试：装饰器 3 + 估算 5 + init 2 + 规则 7）
- 代码风格：`ruff check src/rhythmind/observability/`

---

## 相关文件清单

```
src/rhythmind/observability/
├── __init__.py          # 公开 API: install_metrics, install_tracing
├── metrics.py           # Prometheus 指标定义 + install_metrics
├── tracing.py           # OpenTelemetry 安装 + install_tracing
├── llm_observe.py       # Langfuse 初始化 + @observe_llm 装饰器
└── suggestion_engine.py # 优化建议规则引擎
```

---

## 变更记录 (Changelog)

- **2026-05-21** 新增 Langfuse LLM 观测模块（装饰器 + 规则引擎 + API 路由 + 前端页面）
- **2026-05-12** LoopGuard 新增 `rhythmind_loop_guard_calls_total` Prometheus 指标
- **2026-05-12** 完整扫描完成，新增指标详情
- **2026-05-12** 首次 AI 上下文初始化
