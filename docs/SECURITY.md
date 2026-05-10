# RHYTHMIND 律动 — 安全策略（SECURITY.md）

> 适用版本：0.1.5+
> 维护者：外星动物（常智）/ IoTchange · 14455975@qq.com

本文档说明项目当前的安全模型、已知风险、以及漏洞披露流程。
RHYTHMIND 处理用户健康数据，安全是 P0 优先级。

---

## 1. 漏洞披露（Coordinated Disclosure）

### 1.1 报告渠道

发现安全漏洞请优先**私下**通过以下方式联系，不要公开 issue：

- 邮箱：**14455975@qq.com**（主题以 `[SECURITY]` 开头）
- 加密：可选用项目作者公布的 PGP 公钥（指纹见仓库根 `SECURITY.pubkey`）

请勿在公开 GitHub Issue / 微信群组 / 论坛中披露细节，以免影响在用用户。

### 1.2 报告应包含

- 受影响版本（commit 或 release tag）
- 复现步骤（最好附 PoC 脚本）
- 影响评估（数据泄露 / RCE / 越权 / 拒绝服务）
- 建议修复方案（可选）

### 1.3 响应 SLA

| 严重度 | 首次响应 | 修复目标 |
|---|---|---|
| Critical（RCE / 大规模数据泄露） | 24h | 7 天内发布补丁 |
| High（越权 / 单用户敏感数据泄露） | 72h | 14 天 |
| Medium（DoS / 信息披露） | 5 工作日 | 30 天 |
| Low（最佳实践偏差） | 10 工作日 | 下一次 minor release |

修复完成后，我们会与报告人确认时间窗后协调公开 CVE / Advisory。

### 1.4 致谢

愿意公开身份的报告人会在 release notes 与本文档"致谢"章节署名。

---

> 完整 STRIDE 威胁建模见 [THREAT_MODEL.md](THREAT_MODEL.md)。
> 贡献者安全开发要求见 [../CONTRIBUTING.md §4](../CONTRIBUTING.md#4-安全--合规要求)。

---

## 2. 当前安全模型

### 2.1 信任边界

```
┌──────────────┐    HTTPS+JWT     ┌─────────────┐
│  Client App  │ ────────────────►│   API层      │
└──────────────┘                  └──────┬──────┘
                                         │（内网，私网 IP）
                                         ▼
                              ┌──────────────────┐
                              │ PG / Redis /     │
                              │ Influx / LiteLLM │
                              │ Ollama / QMD     │
                              └──────────────────┘
```

外部请求一律强制 HTTPS + Bearer JWT。内部组件之间走私网，依赖 K8s NetworkPolicy 隔离。模型推理流量（LiteLLM → Anthropic / DeepSeek）允许出公网，但只允许指定的 egress endpoint。

### 2.2 鉴权

- 所有 `/api/v1/*` 路由依赖 `get_current_user_id`（`src/rhythmind/api/deps.py`）
- JWT 验证：HS256 + `JWT_SECRET`（≥32 字符），过期时间默认 24h
- **开发便利通道：** `DEV_AUTH_BYPASS=true` 且 `ENV=dev` 时接受明文 user_id；`ENV=prod` 启动会被 `assert_production_safe()` 拒绝

### 2.3 数据保护

- **传输层：** Ingress 强制 TLS 1.2+；HSTS 已启用；内部 PG 连接建议启用 SSL（`?ssl=require`）
- **静态加密：** 数据库与对象存储（如有）由托管服务负责加密；密钥托管使用 K8s Secret + Sealed-Secrets / Vault
- **PII 边界：**
  - `Sentry` 已配置 `send_default_pii=False`
  - 结构化日志严禁打印请求体（仅记录 `user_id`、`session_id`、路径、状态码）
  - QMD / 技能库存的是模式（patterns），不应包含真实生理指标
- **Loop Guard / Memory：** 用户行为数据按 `user_id` 隔离，跨 user 读写均通过 ORM 强制 user_id 过滤

### 2.4 合规审查

- **前置（PromptAuditor）：** Ollama 本地小模型审查 prompt 意图，BLOCK 即拒绝调用主模型，但**超时降级放行**（性能优先）—— 这是已知折衷
- **后置（ComplianceGate）：** 关键词扫描 + 置信度分级，BLOCK 直接 422

---

## 3. 已知风险与残余威胁（v0.1.5）

| ID | 风险 | 影响 | 当前缓解 | 状态 |
|---|---|---|---|---|
| R-001 | rate limiting 容量与阈值 | 突发流量可耗尽 LLM 配额或拖垮 PG | Redis 双层限流（per-user 30/min + per-IP 60/min on /upload；fail-open 时降级放行） | **已落地**（`api/rate_limit.py`）；阈值需根据真实流量调优 |
| R-002 | 端到端测试覆盖深度 | mock 太多，部分故障路径未覆盖 | 195 unit + 8 integration，含 ASGI + LLM HTTP mock 路径 | **已落地基线**；后续在 staging 跑 Locust（`tests/load/`） |
| R-003 | OTel/Prometheus 接通 | 安全事件可观测性 | `/metrics` + OTel FastAPI instrumentation；PrometheusRule 6 条告警；Grafana dashboard | **已落地**（`observability/`、`charts/rhythmind/`） |
| R-004 | PromptAuditor 超时降级放行 | 审查不可达时合规风险升高 | 后置 ComplianceGate 兜底 | 监控 Ollama 可用率，<99% 触发告警（`RhythmindLLMErrorRateHigh`） |
| R-005 | docker-compose 默认凭据 | 本地开发误暴露公网即被入侵 | `assert_production_safe()` 拒启；docker-compose 改为 `${VAR:?}` 强制 .env | **已缓解**；本地随机化是 nice-to-have |
| R-006 | 健康数据出境 / 数据本地化 | PIPL / GDPR 合规 | LiteLLM 走 Anthropic / DeepSeek 时数据离境 | 客户可设置 `MODEL_PRIMARY_SPEC=ollama://` 全本地路径；数据导出/删除接口已实现（`/api/v1/privacy/*`） |
| R-007 | License 为 CC BY-NC | 商业引入需单独授权 | LICENSE 已说明 | 商业版分支单独评估 |
| R-008 | 用户数据删除幂等性 | 部分外部存储删除失败时如何重试 | DeletionReport 返回每个 store 的 success/failure 明细 | `is_clean=false` 时手工/异步重试；建议补一个 retry job |

---

## 4. 安全开发要求（贡献者须知）

提交 PR 必须满足：

1. **不得引入新的鉴权 bypass**。任何新加的"开发便利"逻辑都必须通过显式开关，且 `assert_production_safe()` 校验通过
2. **新接口必须经过鉴权**：FastAPI 路由签名带 `CurrentUserId`，任何需要登录态的端点不得遗漏
3. **不得直接拼接 SQL**：所有 DB 操作走 SQLAlchemy ORM；动态字段经过 `bindparam`
4. **日志不得打印明文敏感信息**：包括 JWT、API key、请求体、健康指标原始值
5. **依赖更新**：通过 Dependabot / `poetry update`；任何引入的新依赖需在 PR 描述里说明用途
6. **威胁建模触发条件**：以下任一变更必须附 STRIDE 简评 —— 新增外部接口、改鉴权流程、新增数据外送、改密钥/Secret 处理、引入新 LLM 提供商
7. **安全测试**：CI 中的 `ruff` 含部分安全规则；触碰鉴权 / 输入校验代码时必须新增对应单元测试

---

## 5. 安全配置基线（生产）

```bash
# 必须
ENV=prod
DEV_AUTH_BYPASS=false
JWT_SECRET=<openssl rand -hex 32>          # 不在 _SECRET_DEFAULTS_BLOCKLIST
LITELLM_MASTER_KEY=<random>
DATABASE_URL=...?ssl=require               # PG 连接走 TLS
CORS_ALLOW_ORIGINS=https://app.rhythmind.ai
RUN_MIGRATIONS_ON_STARTUP=true             # 配合 initContainer 单实例
SENTRY_DSN=...                             # 启用错误上报（已禁默认 PII）

# 建议
ENFORCE_MODEL_PLATFORM=true
COMPLIANCE_AUDIT_ENABLED=true
LOOP_GUARD_TTL_HOURS=24
LOOP_GUARD_MAX_CALLS=3
```

K8s 侧：

- `runAsNonRoot: true` / `readOnlyRootFilesystem: true` / `allowPrivilegeEscalation: false`
- `seccompProfile: RuntimeDefault`
- `NetworkPolicy` 限制 ingress 源与 egress 目的
- Secret 全部从外部 KMS / Sealed Secrets / Vault 注入，不进 git

---

## 6. 安全事件响应流程

P1 安全事件（疑似数据泄露 / 越权 / RCE）响应步骤：

1. **0–15min：** 隔离 —— 必要时 `kubectl scale --replicas=0` 或下线 Ingress；保留 PG / Redis 当前快照
2. **15min–1h：** 评估影响 —— 拉访问日志，按 user_id 列出受影响用户范围
3. **1–4h：** 修复 —— 在隔离环境复现 / 打补丁 / 紧急部署
4. **4–24h：** 通知 —— 受影响用户与监管（视事件性质）
5. **48h 内：** 复盘 —— 撰写事故报告（时间线、根因、改进项），公开 advisory

---

## 7. 致谢

暂无（项目尚处早期）。欢迎首位安全研究者署名留下足迹 :)
