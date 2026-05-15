# rhythmind/observability — 可观测性

> `[根目录(../../CLAUDE.md) > **rhythmind** > **observability**`

---

## 模块职责

Prometheus 指标 + OpenTelemetry 追踪 + Sentry 错误追踪的安装与暴露。

---

## 入口与启动

- **指标安装**: `install_metrics(app)` — 注册 `/metrics` 端点 + 中间件
- **追踪安装**: `install_tracing(app, service_name)` — OTel FastAPI instrumentation
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

## 关键依赖与配置

- **指标**: `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`
- **Sentry**: `sentry-sdk[fastapi]`
- **配置**: `settings.sentry_dsn`, `settings.env`, `settings.debug`

---

## 数据模型

无持久化数据模型。

---

## 测试与质量

- 测试目录：无专门测试目录（通过集成测试 `tests/integration/` 覆盖）
- 代码风格：`ruff check src/rhythmind/observability/`

---

## 常见问题 (FAQ)

**Q: Sentry 在什么时机初始化？**  
A: `lifespan` startup 阶段，仅在配置了 `SENTRY_DSN` 时启用。

**Q: 如何在业务代码中埋点？**  
A: 直接引用 `HTTP_REQUESTS`, `LLM_CALLS` 等指标对象，调用 `.inc()` 或 `.observe()`。

**Q: prometheus_client 未安装时指标会怎样？**  
A: 指标对象为 no-op，`.inc()` 和 `.observe()` 调用不报错。

---

## 相关文件清单

```
src/rhythmind/observability/
├── __init__.py    # 公开 API: install_metrics, install_tracing, HTTP_REQUESTS, LLM_CALLS, etc.
├── metrics.py     # Prometheus 指标定义 + install_metrics
└── tracing.py     # OpenTelemetry 安装 + install_tracing
```

---

## 变更记录 (Changelog)

- **2026-05-12** LoopGuard 新增 `rhythmind_loop_guard_calls_total` Prometheus 指标
- **2026-05-12** 完整扫描完成，新增指标详情
- **2026-05-12** 首次 AI 上下文初始化
