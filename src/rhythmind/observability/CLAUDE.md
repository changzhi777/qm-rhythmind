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

## OTel 追踪

### install_tracing 初始化

```python
def install_tracing(app: FastAPI, service_name: str = "rhythmind") -> None:
    # 1. 创建 TracerProvider（OTLP exporter → settings.otlp_endpoint）
    # 2. 注册 FastAPIInstrumentor（自动采集 HTTP span）
    # 3. 注入 request_id 到 baggage（跨服务传播）
    # 4. 若 settings.debug，设置全局 propagator 为 composite
```

### Span 属性

| 属性 | 来源 | 说明 |
|------|------|------|
| `http.method` | 自动 | GET/POST/... |
| `http.url` | 自动 | 完整请求 URL |
| `http.status_code` | 自动 | 响应状态码 |
| `user.id` | 自定义 baggage | 当前 user_id |
| `agent.name` | 自定义 attribute | 调用方 Agent 名称 |

## Langfuse v2 表结构适配

LLM 观测 API 使用 Langfuse 内置 PostgreSQL 中的 `observations` 表进行直查：

| 查询字段 | v2 列名 | 旧版列名 | 说明 |
|---------|--------|---------|------|
| 级别/状态 | `level` | `status` | v2 改为 level |
| 总 token | `total_tokens` | JSON 内嵌 | v2 独立列 |
| 总成本 | `total_cost` | JSON 内嵌 | v2 独立列 |
| 延迟计算 | `EXTRACT(EPOCH FROM end_time - start_time)` | — | v2 timestamp 列 |

### @observe_llm 装饰器采集字段

```
@observe_llm(model="gemma-4-e4b", agent="coach_agent")
async def call_llm(messages, temperature, max_tokens):
    ...

自动采集:
  - input: json.dumps(messages)
  - output: str (返回值)
  - metadata: {model, agent, temperature, max_tokens}
  - usage: {input_tokens, output_tokens, total_tokens}
  - cost: 基于 token 数 × 模型单价估算
  - latency_ms: 函数执行耗时
```

## 建议引擎 API

### Suggestion / ModelMetrics

```python
@dataclass
class ModelMetrics:
    model: str
    total_calls: int
    total_tokens: int
    total_cost: float
    avg_latency_ms: float
    error_rate: float
    week_delta_pct: float

@dataclass
class Suggestion:
    rule: str            # 规则名称
    severity: str        # info / warn / critical
    model: str
    detail: str          # 人类可读的建议文本
    evidence: dict       # 触发数据
```

### analyze 端点响应格式

```python
# POST /api/v1/llm-observe/analyze  body: {model?: str, days?: int}
{
    "models": ["gemma-4-e4b-it-4bit", "gpt-4o"],
    "summary": {
        "total_calls": 1523,
        "total_cost": 4.72,
        "avg_latency_ms": 1834
    },
    "suggestions": [
        {"rule": "模型延迟偏高", "severity": "warn", "detail": "gemma-4-e4b 平均延迟 3.2s...", ...}
    ],
    "charts": {
        "cost_trend": [...],      # 近 30 天日成本
        "latency_p50_p95": [...], # 延迟分位数趋势
        "error_rate": [...]       # 错误率趋势
    }
}
```

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充 OTel 追踪安装细节、Span 属性表、Langfuse v2 列名对照、observe_llm 采集字段、建议引擎 API 响应格式
- **2026-05-21** 新增 Langfuse LLM 观测模块（装饰器 + 规则引擎 + API 路由 + 前端页面）
- **2026-05-12** LoopGuard 新增 `rhythmind_loop_guard_calls_total` Prometheus 指标
- **2026-05-12** 完整扫描完成，新增指标详情
- **2026-05-12** 首次 AI 上下文初始化
