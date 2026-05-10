# RHYTHMIND 律动 — 生产就绪度总览（PRODUCTION_READINESS.md）

> 状态截止：2026-05-09 · 版本 0.1.5
> 维护者：外星动物（常智）/ IoTchange · 14455975@qq.com

本文是从 v0.1.1（首版评估）到 v0.1.5（当前）一系列生产硬化轮次的总结，
适合在沟通"是否可以上线"、"还需要什么"时直接对照。

---

## 1. 一句话结论

**应用代码与制品维度已达内部小规模灰度可上线；剩下的是环境配置（Redis ACL、PG 最小权限）、合规法律（PIPL/数据出境告知）、运维流程（备份 PITR 演练）三类，都是代码侧无法闭环的事。**

---

## 2. 一开始的问题清单 vs 现在

下表列出 v0.1.1 评估时识别的 P0 阻断项与 P1 强烈建议项，对照现状：

| 类别 | 起点（v0.1.1） | 现状（v0.1.5） |
|---|---|---|
| **鉴权后门** | `env=dev` 即接受明文 user_id | `dev_auth_bypass` 显式开关 + 生产强制拒；`/mcp/*` 默认要求 Bearer |
| **默认密钥** | `JWT_SECRET=dev-secret-change-in-prod` 硬编码 | `assert_production_safe()` 启动时拒 8 类默认值 + ≥32 字符校验 |
| **CORS** | `*` + `allow_credentials=True` | `CORS_ALLOW_ORIGINS` env 驱动；空 = 拒所有跨域 |
| **Alembic 迁移** | 启动时 `create_all`，docstring 说生产走 alembic 但没接 | 容器入口可选自动 `upgrade head`；K8s 用 Helm pre-install hook 单实例运行 |
| **Dockerfile** | Poetry 路径 + 无 `poetry.lock` + 无 `.dockerignore` | 多阶段非 root（uid 1001）+ `HEALTHCHECK` + entrypoint 二次 secret 校验；CI 强制 lock 同步 |
| **生产模型 spec** | 默认 `mlx://` 进容器 → 必崩 | 启动断言：`mlx://` 不在 Apple Silicon 上拒启 |
| **限流** | 完全没有 | Redis 双层（user 30/min + IP 60/min on /upload）；fail-open；429 + Retry-After |
| **可观测性** | structlog 一条线 | `/metrics` Prometheus（HTTP/LLM/合规/池）+ OTel FastAPI + 6 条 Alert + Grafana dashboard |
| **集成测试** | 0 条 | 19 条（ASGI + ollama HTTP mock + 越权回归 + size limit + MCP auth + audit log） |
| **运维文档** | 仅 ARCHITECTURE.md | DEPLOYMENT / RUNBOOK / SECURITY / THREAT_MODEL / CONTRIBUTING / PRODUCTION_READINESS |
| **K8s 部署** | 仅 docker-compose | 完整 Helm chart（Deployment/Service/HPA/PDB/Ingress/NetworkPolicy/ServiceMonitor/PrometheusRule/dashboard ConfigMap/migration Job）+ `helm lint` CI |
| **数据合规** | 无导出/删除接口 | `GET /api/v1/privacy/export` + `POST /privacy/delete` 覆盖 PG/Redis/Influx/QMD |
| **依赖与镜像扫描** | 无 | CI `dep-audit` (pip-audit, strict) + `image-scan` (trivy CRITICAL/HIGH) + 豁免文件 |
| **审计日志** | 无 | `rhythmind/audit/` 包含 sink 抽象（structlog/InMemory/S3 JSONL）+ 4 个安全关键路径埋点 |
| **测试总数** | README 写 156，实际 195 unit + 0 integration | **214**（195 unit + 19 integration） |

---

## 3. 演进时间线

| 轮次 | 主题 | 关键产出 | 测试数 |
|---|---|---|---|
| v0.1.1 评估 | 识别阻断项 | 评估报告 + P0/P1/P2 优先级清单 | 195 unit |
| **P0** | 上线必修 | 鉴权后门关闭、secret 校验、CORS、Dockerfile、Alembic 接入、健康探针分级、Sentry 真接通、版本号统一 | 195 unit |
| **P1** | 上线必备 | 限流 / Prometheus / OTel / 集成测试雏形 / poetry-lock-check / 三份运维文档 | 195 unit + 6 integration |
| **P2** | 部署制品 | Helm chart 全套、PrometheusRule、Grafana dashboard、LLM 路径 e2e、README/CHANGELOG 同步 | 195 unit + 8 integration |
| **P3** | 合规与压测 | helm-lint CI、`/privacy/export` `/delete`、Locust 压测脚手架 | 195 unit + 13 integration |
| **P4 docs** | 威胁建模 | STRIDE 全组件分析（发现 MCP 鉴权缺口）、CONTRIBUTING、文档交叉链接 | 195 unit + 13 integration |
| **P5** | 威胁建模 follow-up | MCP 鉴权 + 越权回归 + 请求大小限制 + dep-audit/image-scan CI | 195 unit + 19 integration |
| **P6** | 审计 + 严格扫描 | `rhythmind/audit/` + S3 JSONL sink + 4 路径埋点；CI 改 strict + allowlist 文件 | **195 unit + 19 integration** |

每一轮都有：实测数据（pytest 全过）+ 文档同步 + memory 持久化 + 修订总览。

---

## 4. 当前生产风险登记表

按 [THREAT_MODEL.md §5](THREAT_MODEL.md#5-主要残余风险需要排期修) 残余风险表：

| ID | 风险 | 状态 | 责任方 |
|---|---|---|---|
| R-1 | MCP 端点未鉴权 | ✅ 已修 v0.1.5 | — |
| R-2 | 越权回归测试空白 | ✅ 已修 v0.1.5 | — |
| **R-3** | 不可篡改审计日志 | △ 代码骨架已落地（S3JsonlSink），需要 bucket + Object Lock 配置 | **运维** |
| R-4 | Skill / QMD 中毒 | ✅ 已修 v0.1.6（`/api/v1/admin/skills/*` + `skill_require_approval` 开关） | — |
| R-5 | DB 最小权限账号 | ✗ 未修 | DBA：建独立 role + DDL 账号 |
| R-6 | 备份 / PITR 真演练 | ✗ 未修 | 运维：季度演练 |
| R-7 | 依赖 SBOM + 漏洞扫描 | ✅ 已修 v0.1.5（CI strict + allowlist） | — |
| R-8 | Redis ACL | ✗ 未修 | 运维：生产 Redis 配 `requirepass` |
| R-9 | LiteLLM 数据出境告知 | △ 已起草用户告知模板 [docs/legal/DATA_EGRESS_NOTICE_TEMPLATE.md](legal/DATA_EGRESS_NOTICE_TEMPLATE.md)，待法务审阅签发 | 法务 + 产品 |
| R-10 | 请求体大小硬上限 | ✅ 已修 v0.1.5 | — |

**代码侧已完成 5 / 10**；剩 5 项**全部不是代码层能闭环**。

---

## 5. 推荐灰度路径

按从小到大、风险递增的部署节奏：

### 5.1 内部 alpha（now → +1 周）

环境：staging K8s，1 副本，不挂用户域名，仅团队内部测试。

入门动作：
- [ ] 配 Secret：JWT_SECRET（`openssl rand -hex 32`）/ LITELLM_MASTER_KEY / DATABASE_URL（独立 PG 实例）/ INFLUXDB_TOKEN
- [ ] 跑 `bash scripts/bootstrap_lock.sh` 生成 poetry.lock，commit
- [ ] `helm install rhythmind ./charts/rhythmind -f values.staging.yaml`，开 prometheusRule + grafanaDashboard
- [ ] 验证 `/livez` `/readyz` `/metrics` 都正常；Sentry 收到至少 1 条测试事件
- [ ] 跑 [Locust 压测](../tests/load/README.md) 30 分钟，确认 P95 < SLO

### 5.2 内部 beta（+1 → +3 周）

环境：staging 改 2 副本 + HPA 上限 5；接 1 个 staging 域名（HTTPS）。

新增动作（环境侧 R-3..R-9 推进）：
- [ ] **R-3** S3 audit 桶 + Object Lock；`install_audit_sink(S3JsonlSink(bucket="rhythmind-audit-staging"))`
- [ ] **R-5** 把 DSN 切到最小权限账号（`SELECT/INSERT/UPDATE/DELETE` only）
- [ ] **R-8** Redis 开 ACL，凭据进 K8s Secret
- [ ] **R-6** 跑一次 PITR 恢复演练，记录 RTO/RPO 写到 RUNBOOK §2.1
- [ ] **R-4** 把新 Skill 接入 staging collection；`SkillEngine` 加一个 `--require-approval` 标志

### 5.3 公测灰度（+3 → +6 周）

环境：生产 K8s，HPA 2-10；接生产域名；Cloudflare/WAF 在前。

新增动作：
- [ ] **R-9** 用户协议明确"使用云端模型时数据可能离境"；强制本地化客户配置 `MODEL_PRIMARY_SPEC=ollama://`
- [ ] PIPL 备案 + 个保影响评估（如适用）
- [ ] 把 PrometheusRule 接到 Alertmanager → 飞书/PagerDuty
- [ ] 公测白名单从 50 → 500 → 5000 用户分阶段放量

### 5.4 全量上线（+6 周以后）

环境：生产 K8s，多区域备份；Locust 压测每周自动跑一次；故障演练每季度一次。

---

## 6. 环境侧检查清单（go-live 前）

代码侧已经准备好；这个清单是给运维 / DBA / 法务的：

```
[ ] K8s namespace + RBAC 隔离
[ ] Secret 来源不是 git；用 SealedSecret / ExternalSecret / Vault
[ ] PG 启用 TLS（DATABASE_URL 含 ?ssl=require）+ 备份 + WAL-G PITR
[ ] Redis 启用 ACL/`requirepass`
[ ] InfluxDB token 至少 24 字符随机；按用户写入 tag 隔离已就绪
[ ] LiteLLM master_key ≥ 16 字符；外部 API key 90 天轮换流程
[ ] Ingress 强制 TLS 1.2+；HSTS / CSP / X-Frame-Options 配齐
[ ] WAF 规则：拦截常见 SQLi / XSS / 路径遍历；对 /health/upload 加 IP 限速
[ ] PrometheusRule 接 Alertmanager；6 条 Alert 都收到测试通知
[ ] Grafana dashboard 已导入；oncall 每天看一眼
[ ] Sentry DSN 配置；`send_default_pii=False` 已生效
[ ] 用户协议含数据出境告知 + 合规联系人邮箱
[ ] 用户可见的"导出/删除"入口在前端打通到 /privacy/* API
[ ] 故障 / 安全事件 oncall 联系人在 RUNBOOK §9 已更新
[ ] 备份恢复演练至少 1 次成功记录
```

---

## 7. 联系

技术问题 / 商业授权：14455975@qq.com（changzhi777@gmail.com）

安全漏洞披露：见 [SECURITY.md §1](SECURITY.md#1-漏洞披露coordinated-disclosure)

贡献代码：见 [CONTRIBUTING.md](../CONTRIBUTING.md)
