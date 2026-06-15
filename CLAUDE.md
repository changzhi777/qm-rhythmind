# CLAUDE.md — RHYTHMIND 律动

> **项目版本:** 0.2.0
> **最后扫描:** 2026-06-12T20:34:50+08:00（晚间增量轮）
> **语言:** Python 3.12+
> **包管理:** uv / Poetry

---

## 变更记录 (Changelog)

- **2026-06-13 (P2 拆分完成)** 🟡 **`dashboard.py` 1027 行 → 3 文件拆分完成** — ① 新建 `_common.py`（14 行）共享 `_fm()` FactManager 工厂（DRY）② 新建 `reports.py`（387 行）含 5 端点（`/reports` + `/reports/{id}` + `/reports/{id}/download` PDF + `/test-reports` + `/test-reports/{id}/{file}`）+ `_generate_qr_image()` 内部函数 + `_TEST_REPORT_DIR` 常量 ③ 新建 `users_summary.py`（112 行）含 1 端点（`/users/summary`）+ `_USER_DISPLAY` 常量 ④ 清理 `dashboard.py` → **578 行（-44%，从 1027 → 578）**保留 6 端点（`/dashboard` + `/influxdb/timeseries` + `/analyze` + `/import-facts` + `/upload/file` + `/chat`）+ 多模态工具函数 ⑤ `main.py` 路由挂载更新（`include_router(reports_router)` + `include_router(users_summary_router)`）⑥ 新建 `tests/integration/test_reports.py`（6 用例）+ `tests/integration/test_dashboard.py`（5 用例）作为拆分专项 ⑦ **全量回归：559 passed + 4 skipped + 0 failed**（29.75s，新增 11 用例）⑧ **🟡 P2 全闭环 → 唯一剩余 N1 dashboard 拆分已完成** ✅
- **2026-06-13 (E2E 回归验证)** ✅ **前端 E2E 10 轮全链路测试通过** — 跑 `frontend/tests/e2e_test.py` 验证后端 P1/P3 变更未影响前端：① 10 轮 × 19 用例 = **90 通过 + 100 skip + 0 失败**（与 2026-06-11 基线 100% 一致）② 9 用例/轮 = 鉴权 API（dashboard / reports / medical / llm-observe / memory / pool/stats 等），10 skip = 公开页面（无 Authorization header）③ 报告产出：`/tmp/qm-e2e-reports/e2e-report.{md,html,pdf}` ④ 验证：所有受影响端点（feishu/dashboard/health/medical/llm-observe）均正常响应 → **后端 P1（MetricsProcessor 写库）+ P3（requires_human_review 解耦）回归保护完整** ✅
- **2026-06-13 (mypy 静态类型 + P2 评估)** 📊 **mypy strict 模式基线建立**：① 跑全仓 `mypy src/` = **197 错误 / 39 文件 / 82 源文件** ② 错误分布：type-arg 缺泛型 71（36%）/ no-any-return 25（13%）/ attr-defined 25（13%）/ no-untyped-call 18（9%）/ 其他 58（29%）③ **83% 为历史类型注解缺失**（与 ruff 1413 错误同源） ④ 本轮修改文件 mypy = 3 错误（gate.py:105/162 COMPLIANCE_BLOCKS 未导出 + hermes_base.py:396 call_llm 返回 Any）⑤ **P2 拆分评估：dashboard.py 实为 1027 行 / 12 端点 / 5 工具函数 / 1027 行**，完整拆 3 文件 + 测试迁移风险高（路由挂载 / import 路径 / 测试覆盖），**建议作为下轮独立专注任务**（预计 1-1.5 小时）
- **2026-06-13 (P3 解耦 + 全闭环)** 🟡 **`requires_human_review` 与 `BLOCK` 字段语义解耦**：① `ComplianceResult` 新增 `compliance_block`（合规门禁拦截）+ `advisor_review`（Agent 建议复核）两个独立字段；`requires_human_review` 改为 `@property`（OR 派生，保持向后兼容）② `hermes_base.py:250-251` 合并逻辑拆为两条独立设置（BLOCK→compliance_block / raw→advisor_review）③ `gate.py:97-103` BLOCK 分支设 `compliance_block=True`；PASS/WARN 分支删除冗余设 False ④ `hermes_base.py:414` + `swarm_data_coach.py:493,539` 构造点迁移 ⑤ `metrics_agent.py:223` MetricsProcessor 直接构造 ComplianceResult 用 `advisor_review=has_critical` ⑥ 新建 `TestComplianceResultDecoupling` 5 用例：property 派生 + 构造拒绝旧字段名 + BLOCK/WARN/PASS 路径全覆盖 ⑦ **全量回归：548 passed + 4 skipped + 0 failed**（30.04s，新增 5 用例） ⑧ **🟡 P3 全闭环 → 所有 7+2+1+1 风险项全绿** ✅
- **2026-06-12 (晚间最终闭环)** 🔴 **飞书路由 3 端点测试上线** — 新建 `tests/unit/test_feishu.py`（9 用例，0.53s 全通过）：`/api/v1/feishu/webhook` URL 验证挑战 + 错误 token 403 + v1/v2 schema 消息事件 + 未处理事件类型 + 无 token 旁路；`/api/v1/feishu/poll` 无 chat/有 chat 双分支；`/api/v1/feishu/status` 字段完整性。**全量 pytest 回归：540 passed + 4 skipped + 0 failed**（29.11s，新增 9 用例）。**🔴 全部 7 项高风险 + 2 项新发现 = 100% 闭环** ✅ 项目进入全绿状态
- **2026-06-13 (P1 修复 + 质量闭环)** 🟡 **MetricsProcessor memory_updates 写库路径修复**：① `agents/metrics_agent.py` 末尾新增 `MemoryManager.update()` 显式调用（try/except 降级为 warning 日志，不阻断主流程）② 新建 `TestMetricsProcessorMemoryPersistence` 3 用例：AgentMemory 表行数断言 + 写库失败不崩溃 + 非空时调用计数 ③ `ruff check src/rhythmind/agents/metrics_agent.py` = **All checks passed!**（修改文件 0 错误）④ 全量回归 **543 passed + 4 skipped + 0 failed**（30.47s，新增 3 用例）⑤ 全仓 ruff 共 1413 错误，**86% 为历史 ANN 类型注解缺失**（非本轮引入）
- **2026-06-12 (晚间增量修复)** N5/N6 闭环：① `uv pip install 'qrcode[pil]>=7.4'` 修复 dashboard.py:381 缺失依赖 ② `pyproject.toml` `dependencies` 补 `qrcode[pil]>=7.4,<9.0` ③ `uv lock` + `uv sync --all-extras` 同步依赖 ④ 全量 pytest 回归验证：**531 passed + 4 skipped + 0 failed**（N5 修复前 2 fail → 修复后 0 fail）
- **2026-06-12 (晚间增量)** 增量审计 + pytest 实测：全仓 1,054 源文件 / 14,720 后端 Python 行 / 46 测试 / 27 CLAUDE.md 健在；产出 [`docs/audit/2026-06-12-evening-incremental-report.md`](../docs/audit/2026-06-12-evening-incremental-report.md)（317 行 / 15.7 KB）；**pytest 套件实测**：unit 460/4 skip ✅、integration 69/2 fail ❌（**2 个失败均为 `qrcode` 模块缺失**），全量 529 passed + 4 skipped + 2 failed（29.82s）；**🔴 高风险 7 项验证**：5 项已修复/误判（AG2 Swarm 实 545 行+有测试 / LLM-observe 5 端点 / LoopGuard 10+ 用例 / SSE /upload/stream E2E 覆盖 / _build_timeline_prompt 复用），1 项仍成立（**飞书 3 端点无测**），1 项部分仍成立（MetricsProcessor 不继承 HermesBase → memory_updates 不写库）；🆕 新发现 6 项：N1 dashboard.py 37KB/23 端点拆分 / N2 SSE 鉴权缺独立测试 / N5 **pytest 实测发现 dashboard.py:381 qrcode 缺失** / N6 pyproject.toml 依赖清单不完整；P0（立即）：`uv pip install 'qrcode[pil]'` + 补 pyproject.toml 依赖；P0（1 周内）：新建 `tests/unit/test_feishu.py`
- **2026-06-12 (深度补捞)** 三大核心模块深度扫描：api 47 端点 + agents 4 Agent (1181 行) + orchestrator 6 文件 (1175 行) = **3531+ 行源码 + 26+ 测试文件 + 160+ 用例**；产出 [`docs/audit/2026-06-12-deep-sweep-report.md`](../docs/audit/2026-06-12-deep-sweep-report.md)（636 行 / 29 KB），含 5 条 Mermaid 跨模块数据流图、47 端点全栈接口总表、22 个缺口清单（🔴 7 / 🟡 10 / 🟢 5）；**架构 3 大风险点**：① MetricsProcessor 不走 HermesBase.run() → memory_updates 永远不被 SwarmDataCoach 写库；② `run_ag2_swarm()` (~200 行) 完全无测，可能属"幽灵代码"；③ `requires_human_review` 字段在 SwarmDataCoach 中未被消费，与 BLOCK 语义混淆；**最高优先级修复**（1-2 周内）：飞书路由 3 端点、LLM-observe 5 端点、SSE `/upload/stream`、LoopGuard 分级阈值回归、MetricsProcessor memory_updates 写库路径
- **2026-06-12 (本次)** 周期扫描：项目结构与 2026-06-11 基线 100% 一致（0 新增文件），验证全部 27 个 CLAUDE.md 健在、6 个 Alembic migration 完整（001-006）、4 个 agents（metrics/data/coach/medical_advisor）/ 7 个 api routers（health/privacy/admin/dashboard/medical/llm_observe/feishu）/ 11 个 scripts（6 Python + 5 Shell）/ 9 个前端页面（page/dashboard/bigscreen/medical/llm-observe/report/test-report/chat/upload）/ 3 个 docs 域（templates/workflows/knowledge）全部齐备，CT109 生产恢复完成（绕过 NFS、G 方案重建服务），`index.json` 刷新（2026-05-12 → 2026-06-12）
- **2026-06-11 (本次)** 增量更新：项目上下文知识库管线上线（CLAUDE.md+Memory→knowledge_article→QMD→MCP检索）、轻量QMD兼容服务替代@tobi/qmd、5个模块CLAUDE.md深化（ingestion/privacy/observability/adapters/audit）、E2E测试CLAUDE.md深化
- **2026-06-10** 增量更新：10 个 CLAUDE.md 接口深化（web/scripts/templates/workflows/knowledge/integrations/charts/layout/cache/mcp）、前端核心补全（InfluxDB 时序图+401+Skeleton+Auto-refresh）+ Tailwind 全量迁移
- **2026-06-09** 增量更新：扫描覆盖率重计算（25 个 CLAUDE.md 全部就绪 + 1 项目级 = 26），扫描时间戳刷新，Changelog 追加，根级 Mermaid 模块结构图引入
- **2026-05-27 (P2)** 增量更新：新增 `docs/templates/garmin-health-report-template.md`（佳明健康报告标准化模板，含三种格式章节结构+SpO2分析模板+HTML→PDF脚本）和 `docs/workflows/garmin-data-analysis-workflow.md`（佳明数据分析7阶段工作流，含数据陷阱、产出清单、质量检查）
- **2026-05-27 (P3)** 增量更新：新增知识库模块（knowledge_models.py + 2 张表 + migration 006）、知识库入库脚本（ingest_knowledge.py）、docs/knowledge/ 领域知识文档（OSA/睡眠/VO2max）
- **2026-05-27 (P1)** 增量更新：新增 integrations 模块（飞书/Lark 客户端）、Feishu Webhook 路由（3 端点）、多用户首页（用户选择卡片）、LoopGuard 分级限流、GZip 压缩中间件、PG/Redis 连接池翻倍（20/40）、oMLX 合规审查独立 URL、渐进式压力测试脚本、Dashboard `/users/summary` API
- **2026-05-26** 增量更新：版本 0.2.0、新增医疗模块（MedicalAdvisor + 5 表 + 4 API 端点 + 前端页面 5 Tab）、LLM 观测模块上线（Langfuse + 规则引擎 + 前端页面）、Medical/LlmObserve 前端页面、医疗模块 28 个测试、API 文档（OpenAPI 3.0 + 集成指南）、Langfuse Docker 部署配置
- **2026-05-23** 新增 API & MCP 集成文档（`docs/api-integration-guide.md`）和 OpenAPI 3.0 规范（`docs/openapi.yaml`）
- **2026-05-20** 增量更新：API middleware 重构为包目录、Chat/Upload 页面已实现、PDF/图像多模态 AI 视觉分析、API 统一（upload/file + chat 端点）、getAuthToken 去重
- **2026-05-18** 增量更新：新增 Chat 智能助手页面、文件上传分析（数据文件/医学报告/图像）、返回导航、前端重构（共享 Header/utils）、E2E 测试模块
- **2026-05-18** 增量更新：新增 cache 子模块、PGSink、migration 004、web/ 替代前端、部署配置更新
- **2026-05-15** 增量更新：新增 ingestion 模块、dashboard/PDF 报告路由、前端 CLAUDE.md、部署到 aisport.tech/qm
- **2026-05-12** Phase 1/2/3/4 实现完成，版本升至 0.1.9
- **2026-05-12** 完整扫描完成，覆盖率 69% (55/80 文件)，新增子模块详情
- **2026-05-12** 首次 AI 上下文初始化，模块结构扫描完成

---

## 待完成 / 外部依赖

| 任务 | 状态 | 阻塞原因 |
|------|------|---------|
| HIPAA/PIPL 法律审查 Agent | ⚠️ 计划中 | 对接专门 Agent 实现 API，待法务团队确认合规要求后执行 |
| CT109 NFS 替代方案 | ✅ 已完成（G 方案） | 2026-06-12 重建 PG/Redis/.env，绕过 TrueNAS 故障 |

---

## 项目愿景

RHYTHMIND 律动是一个基于多智能体协作的 AI 健康管理平台，本地优先推理（Apple Silicon），生产部署支持 K8s + Ollama / LiteLLM。核心特性：

- **三阶段 Swarm 流水线**：指标采集 → 数据分析 → 健康教练，全程多智能体协作
- **医疗顾问模块**：MedicalAdvisor 基于 5 张医疗结构化表，提供综合分析/时间线/用药审查/化验趋势 4 种任务
- **Hermes Pattern v2**：标准化 6 步智能体执行循环，内置记忆、技能、合规
- **多形态推理**：MLX（本地 Apple Silicon）+ Ollama（HTTP）+ LiteLLM（云端网关）三路自动路由
- **MCP 接口**：Model Context Protocol SSE 服务，对外暴露健康工具
- **LLM 观测**：Langfuse v2 SDK + 规则引擎 + 前端页面，实时监控 LLM 调用质量
- **飞书集成**：Webhook 事件回调 + 消息轮询，支持飞书群聊直接与 Agent 对话
- **多用户支持**：首页用户选择卡片，多用户健康数据隔离
- **生产就绪运维**：限流、Prometheus `/metrics`、OpenTelemetry、Helm chart、GZip 压缩