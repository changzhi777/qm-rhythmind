# LLM 观测模块开发计划

> 创建时间: 2026-05-21T16:03:00+08:00
> 状态: 待批准

## 上下文

为 RHYTHMIND 增加 LLM 观测模块，集成 Langfuse SDK v4（@observe 装饰器），
自托管 Langfuse Server（纯 PG 模式），前端新增 `/llm-observe` 观测页面，
含 ECharts 组件 + 规则引擎优化建议 + LLM 深度分析。

## 技术选型

| 技术 | 用途 |
|------|------|
| Langfuse SDK v4 (`langfuse`) | Python LLM Tracing，@observe 装饰器 |
| Langfuse Server v3 (Docker) | 自托管，纯 PG 模式，无 ClickHouse |
| PostgreSQL (共享) | Langfuse 复用 RHYTHMIND 现有 PG 实例 |
| ECharts 6 | 前端观测图表（趋势/成本/健康度） |
| 规则引擎 | 基于阈值的实时优化建议 |

---

## 阶段 1：基础设施（Langfuse Server）

### 步骤 1.1：创建 docker-compose.langfuse.yml

- 文件：`deploy/docker-compose.langfuse.yml`
- 内容：Langfuse v3 + PostgreSQL 服务定义
  - 环境变量：`DATABASE_URL` 指向 PG，`LANGFUSE_DISABLE_CLICKHOUSE=true`
  - 端口映射：`3020:3000`
  - PG 使用独立数据库 `langfuse_db`（同实例，不同 DB）
  - `S3_EVENT_UPLOAD_DISABLED=true`（禁用 S3）
- 预期：`docker compose up -d` 启动后 Langfuse UI 可访问

### 步骤 1.2：创建 PG 数据库 + 用户

- 在现有 PG 实例上创建 `langfuse_db` 数据库
- SQL：`CREATE DATABASE langfuse_db;`

### 步骤 1.3：Nginx 反向代理

- 在 aisport.tech nginx 配置中增加 `/qm/llm-observe` 反代到 Langfuse
- 用于开发者直接访问 Langfuse UI（前端观测页面走后端 API）

### 步骤 1.4：配置 Langfuse 项目

- 访问 Langfuse UI，创建项目，获取 Public Key + Secret Key
- 记录到 `settings` 配置中

---

## 阶段 2：后端 — Langfuse SDK 集成

### 步骤 2.1：添加依赖

- 文件：`pyproject.toml`
- 新增：`langfuse>=4.0,<5` 依赖
- 执行：`pip install langfuse`

### 步骤 2.2：配置项

- 文件：`src/rhythmind/config.py`
- 新增 Settings 字段：
  - `langfuse_public_key: str = ""`
  - `langfuse_secret_key: str = ""`
  - `langfuse_host: str = "http://localhost:3020"`（自托管地址）
  - `langfuse_enabled: bool = False`
  - `langfuse_db_url: str = ""`（直查 PG 连接串）
- 预期：环境变量控制 Langfuse 开关

### 步骤 2.3：创建观测装饰器模块

- 文件：`src/rhythmind/observability/llm_observe.py`
- 类/函数：
  - `init_langfuse()` — 初始化 Langfuse 客户端（读取 settings）
  - `@observe_llm(model, agent)` — 装饰器，封装 Langfuse `@observe`
    - 自动捕获 input/output
    - 记录 model、temperature、max_tokens
    - 记录 usage_details（input/output tokens）
    - 记录 cost_details
    - 记录 latency_ms
    - Langfuse 禁用时退化为 no-op（零开销）
  - `get_langfuse()` — 获取 Langfuse 单例
- 预期：装饰器可独立测试，Langfuse 不可用时静默降级

### 步骤 2.4：嵌入 AdapterRouter.generate()

- 文件：`src/rhythmind/adapters/adapter_router.py`
- 修改：`AdapterRouter.generate()` 方法加 `@observe_llm` 装饰器
- 嵌入后：所有通过 AdapterRouter 的 LLM 调用自动采集
- 预期：不改业务逻辑，一行装饰器完成埋点

### 步骤 2.5：应用启动时初始化

- 文件：`src/rhythmind/api/main.py`
- 修改：`lifespan()` 启动阶段调用 `init_langfuse()`
- 预期：`langfuse_enabled=True` 时自动连接 Langfuse Server

---

## 阶段 3：后端 — 观测 API 路由

### 步骤 3.1：创建 LLM 观测 API 路由

- 文件：`src/rhythmind/api/routers/llm_observe.py`
- 端点：
  - `GET /api/v1/llm-observe/metrics` — 汇总指标
    - 直查 Langfuse PG：总调用数/成功率/平均延迟/P95延迟/token消耗/总成本
    - 按模型分组、按天分组
    - 参数：`days=7`（默认近 7 天）
  - `GET /api/v1/llm-observe/traces` — Trace 列表
    - 直查 PG：最近 N 条 Trace，含 user_id/session_id/model/latency/status
    - 参数：`limit=50, offset=0, model=None, agent=None`
  - `GET /api/v1/llm-observe/traces/{id}` — Trace 详情
    - 含完整 input/output/metadata/tokens/cost
  - `GET /api/v1/llm-observe/suggestions` — 规则引擎优化建议
    - 直查 PG 聚合数据 + 规则引擎生成建议列表
  - `POST /api/v1/llm-observe/analyze` — LLM 深度分析
    - 聚合近 N 天数据 + prompt → LLM 生成优化报告（流式 SSE）
- 预期：5 个端点，认证保护（复用 CurrentUserId）

### 步骤 3.2：创建规则引擎

- 文件：`src/rhythmind/observability/suggestion_engine.py`
- 函数：
  - `generate_suggestions(metrics: dict) -> list[Suggestion]`
  - 规则：
    - 模型延迟对比（P95 > 2x 均值）
    - Token 利用率（output/input < 5%）
    - 成本周环比（增长 > 30%）
    - 错误率（某模型 > 5%）
    - 重复 Prompt（相似 prompt > 10 次/小时）
- 数据模型：`Suggestion(title, severity, detail, metric_key, current_value, threshold)`
- 预期：纯函数，无 LLM 依赖，可独立测试

### 步骤 3.3：注册路由

- 文件：`src/rhythmind/api/main.py`
- 修改：`app.include_router(llm_observe_router, prefix="/api/v1")`

---

## 阶段 4：前端 — 观测页面

### 步骤 4.1：创建 Zustand Store

- 文件：`frontend/src/lib/stores/llm-observe-store.ts`
- 状态：
  - `metrics: LLMMetrics | null`（汇总指标）
  - `traces: Trace[]`（Trace 列表）
  - `suggestions: Suggestion[]`（优化建议）
  - `analysisReport: string`（LLM 分析报告）
  - `loading: boolean`
  - `error: string | null`
- Actions：`fetchMetrics`, `fetchTraces`, `fetchSuggestions`, `runAnalysis`

### 步骤 4.2：创建 ECharts 组件

- 文件：`frontend/src/components/llm-observe/`
  - `llm-trend-chart.tsx` — 调用趋势折线图（调用量/延迟/token，按天分组）
  - `cost-card.tsx` — 成本统计卡片（总成本/按模型分布/日趋势迷你图）
  - `model-health-gauge.tsx` — 模型健康度仪表盘（成功率/延迟评分）
  - `trace-list.tsx` — Trace 列表（表格 + 展开详情）
  - `optimization-panel.tsx` — 优化建议卡片列表
  - `ai-analysis-button.tsx` — 触发 AI 深度分析按钮

### 步骤 4.3：创建观测页面

- 文件：`frontend/src/app/llm-observe/page.tsx`
- 布局：
  ```
  Header（导航栏）
  ┌──────────────────────────────────────┐
  │ KPI 卡片行：总调用 | 成功率 | 平均延迟 | 总成本  │
  ├──────────────────────────────────────┤
  │ LLMTrendChart (调用趋势)              │
  ├──────────────────────────────────────┤
  │ ModelHealthGauge | CostCard          │
  ├──────────────────────────────────────┤
  │ OptimizationPanel (优化建议)          │
  ├──────────────────────────────────────┤
  │ AIAnalysisButton                      │
  ├──────────────────────────────────────┤
  │ TraceList (可展开详情)                 │
  └──────────────────────────────────────┘
  ```
- 预期：~250 行，深色主题，与现有页面风格一致

### 步骤 4.4：导航入口

- 文件：`frontend/src/components/layout/header.tsx`
- 修改：导航栏增加 "LLM 观测" 链接 → `/llm-observe`

---

## 阶段 5：测试

### 步骤 5.1：后端单元测试

- 文件：`tests/unit/test_llm_observe.py`
- 覆盖：
  - `@observe_llm` 装饰器：正常采集 / Langfuse 禁用时 no-op / token 记录
  - `SuggestionEngine`：5 条规则各 1 个测试
  - 观测 API 端点：metrics/traces/suggestions 的 mock 测试
- 预期：~25 个测试

### 步骤 5.2：前端验证

- 启动 dev server，验证页面渲染、数据加载、图表交互

---

## 阶段 6：部署

### 步骤 6.1：服务器部署 Langfuse

- `scp docker-compose.langfuse.yml` 到服务器
- 创建 PG 数据库
- `docker compose up -d`
- 配置 Nginx 反代

### 步骤 6.2：更新 RHYTHMIND 配置

- 设置环境变量：`LANGFUSE_ENABLED=true`, `LANGFUSE_HOST`, keys 等
- 重启 uvicorn

### 步骤 6.3：重新构建前端

- `npm run build` → 部署到服务器

---

## 文件清单

```
新增文件：
  deploy/docker-compose.langfuse.yml       # Langfuse Docker 部署
  src/rhythmind/observability/llm_observe.py     # @observe_llm 装饰器
  src/rhythmind/observability/suggestion_engine.py # 规则引擎
  src/rhythmind/api/routers/llm_observe.py       # 观测 API 路由
  tests/unit/test_llm_observe.py                 # 单元测试
  frontend/src/lib/stores/llm-observe-store.ts   # 前端状态
  frontend/src/components/llm-observe/            # 观测组件目录
  frontend/src/app/llm-observe/page.tsx           # 观测页面

修改文件：
  pyproject.toml                                  # +langfuse 依赖
  src/rhythmind/config.py                         # +Langfuse 配置项
  src/rhythmind/adapters/adapter_router.py        # +@observe_llm 装饰器
  src/rhythmind/api/main.py                       # +init_langfuse + 路由注册
  frontend/src/components/layout/header.tsx       # +导航入口
```
