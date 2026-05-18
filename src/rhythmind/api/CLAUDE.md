# rhythmind/api — FastAPI REST API 层

> `[根目录](../../../../CLAUDE.md) > **rhythmind** > **api**`

> **最后更新:** 2026-05-18T13:24:25+08:00

---

## 变更记录

- **2026-05-18** 增量更新：新增 test-reports 端点、认证下载、Chat/Upload 端点规划
- **2026-05-18** 增量更新：dashboard 路由前缀从 `/qm` 改为 `/qm/api`
- **2026-05-15** 新增 dashboard 路由（仪表盘 + PDF 报告生成），更新端点列表
- **2026-05-12** 完整扫描完成，新增端点详情和数据模型

---

## 模块职责

FastAPI 应用入口，提供 REST API、MCP SSE 路由、健康检查、认证中间件、限流、仪表盘数据、PDF 报告生成、Chat 对话、文件上传等。

---

## 入口与启动

```bash
uvicorn rhythmind.api.main:app --reload --port 8000
```

**应用实例**: `rhythmind.api.main.app`

**生命周期** (`lifespan`):
1. `assert_production_safe()` — 生产配置安全断言
2. Alembic 自动迁移（可选，`RUN_MIGRATIONS_ON_STARTUP=True`）
3. `init_db()` 兜底建表
4. Sentry 初始化（若配置 `SENTRY_DSN`）
5. AgentPool 后台清理任务（每 5 分钟）

---

## 对外接口

### 路由列表

| 路由 | 前缀 | 用途 |
|------|------|------|
| `health_router` | `/api/v1` | 健康检查相关 |
| `privacy_router` | `/api/v1` | 用户数据导出/删除 |
| `admin_router` | `/api/v1` | Admin 技能审批 |
| `dashboard_router` | `/qm/api` | 仪表盘 + AI 报告 + PDF 下载 |
| `mcp_router` | `/mcp/*` | MCP SSE + 消息处理 |

### 健康检查端点

| 端点 | 用途 |
|------|------|
| `GET /livez` | K8s livenessProbe（仅进程存活） |
| `GET /readyz` | K8s readinessProbe（含 DB/Redis 检查，可选 LLM） |
| `GET /health` | 兼容旧 LB |
| `GET /ping` | 兼容旧脚本 |
| `GET /version` | 版本信息（含 git_sha, build_time） |

### MCP 端点

| 端点 | 用途 |
|------|------|
| `GET /mcp/sse` | SSE 长连接 |
| `POST /mcp/messages/` | 消息处理 |

### 健康数据端点

| 端点 | 用途 |
|------|------|
| `POST /api/v1/health/upload` | 上传健康数据（同步） |
| `POST /api/v1/health/upload/stream` | 上传健康数据（SSE 流式） |
| `WS /api/v1/health/upload/stream/ws` | 上传健康数据（WebSocket 流式） |
| `POST /api/v1/health/ingest` | 可穿戴设备 CSV 数据摄入 |
| `POST /api/v1/health/chat` | 文本对话（意图分类） |
| `GET /api/v1/health/memory` | 用户记忆摘要（仅 debug） |
| `GET /api/v1/health/pool/stats` | Agent 池诊断（仅 debug） |

### Dashboard 端点

| 端点 | 用途 |
|------|------|
| `GET /qm/api/dashboard` | 仪表盘汇总数据 |
| `GET /qm/api/reports` | AI 分析报告列表 |
| `GET /qm/api/reports/{id}` | 单篇报告详情 |
| `GET /qm/api/reports/{id}/download` | 下载报告 PDF（含 QR 码） |
| `POST /qm/api/analyze` | 触发本地模型重新分析 |
| `POST /qm/api/import-facts` | 批量导入健康事实数据 |
| `GET /qm/api/test-reports` | E2E 测试报告列表 |
| `GET /qm/api/test-reports/{id}/{file}` | 下载测试报告文件 |

**PDF 生成特性**：
- 使用 ReportLab + STHeiti Light 中文字体
- 自动清理 LaTeX 数学表达式
- 右上角二维码（`rhythmind.cn` 链接）
- 页数控制在 2 页内
- 底部 Pro 订阅提示 + 公司版权声明

---

## 关键依赖与配置

- **Web**: `fastapi`, `uvicorn[standard]`, `sse-starlette`
- **中间件**: CORS、请求体大小限制 (`RequestSizeLimitMiddleware`)
- **可观测性**: `install_metrics()` (Prometheus), `install_tracing()` (OTel)
- **依赖注入**: `api/deps.py` — `get_current_user_id()`, `get_router()`, `get_pool()`

---

## 数据模型

无持久化数据模型，通过 SQLAlchemy 与 `db/models.py` 交互。

**Schemas** (`api/schemas/health.py`):
- `HealthDataUploadRequest` — 上传请求
- `HealthChatRequest` — 对话请求
- `WorkflowResultResponse` — 统一响应格式
- `HRZones` — 心率区间

---

## 测试与质量

- 测试目录：`tests/` 下有集成测试
- 代码风格：`ruff check src/rhythmind/api/`

---

## 常见问题 (FAQ)

**Q: 如何添加新的 API 路由？**  
A: 在 `api/routers/` 下创建新文件，导入并挂载到 `main.py` 的 `app.include_router()`。

**Q: 生产环境 CORS 如何配置？**  
A: 通过 `CORS_ALLOW_ORIGINS` 环境变量配置，`ENV=prod` 时必须显式提供。

**Q: dev_auth_bypass 的安全边界？**  
A: 仅在 `ENV!=prod` 且 `dev_auth_bypass=True` 时生效；`ENV=prod` 时 `assert_production_safe()` 直接拒启。

---

## 相关文件清单

```
src/rhythmind/api/
├── __init__.py
├── main.py              # FastAPI 应用入口 + lifespan
├── deps.py              # 依赖注入 (JWT, HealthRouter, AgentPool)
├── rate_limit.py        # Redis 固定窗口限流 (per-user/per-IP)
├── middleware.py        # 请求体大小限制中间件
├── routers/
│   ├── health.py        # 健康数据上传 / SSE 流 / 文本对话 / CSV 摄入
│   ├── dashboard.py     # 仪表盘 / AI 报告 / PDF 下载 / 测试报告
│   ├── privacy.py       # GDPR/PIPL 数据导出删除
│   └── admin.py         # Admin 技能审批
└── schemas/
    └── health.py        # Pydantic 请求/响应模型
```

---

## 变更记录 (Changelog)

- **2026-05-18** 增量更新：dashboard 路由前缀从 `/qm` 改为 `/qm/api`
- **2026-05-15** 新增 dashboard 路由（仪表盘 + PDF 报告生成），更新端点列表
- **2026-05-12** 完整扫描完成，新增端点详情和数据模型
- **2026-05-12** 首次 AI 上下文初始化
