# RHYTHMIND 律动 — 运维手册（RUNBOOK.md）

> 适用版本：0.1.5+
> 适用对象：Oncall 工程师、SRE
> 默认环境：K8s（namespace = `rhythmind`）

本文档列举常见故障的现象、定位与处置流程。所有命令默认在生产 K8s context 下执行。

---

## 0. 通用排查工具箱

```bash
# 进入任意 API Pod
kubectl -n rhythmind exec -it deploy/rhythmind-api -- bash

# 实时日志（结构化 JSON）
kubectl -n rhythmind logs -f deploy/rhythmind-api --tail=200 | jq .

# 健康探针
kubectl -n rhythmind port-forward deploy/rhythmind-api 8000:8000 &
curl -fsS http://localhost:8000/livez   # 进程存活
curl -fsS http://localhost:8000/readyz  # 流量准备（含 DB/Redis 检查）

# 查 LoopGuard / 会话缓存
kubectl -n rhythmind exec deploy/rhythmind-redis -- redis-cli KEYS 'loop:*'
```

事故响应模板：

> 1. 在 IM 群同步现象与时间窗
> 2. 看 `/readyz` 与 Sentry 最近 5 分钟事件
> 3. 看 Grafana 「rhythmind-overview」面板（HTTP 5xx、LLM P95、Pool 命中率）
> 4. 走下面对应章节定位
> 5. 处置 + 复盘

---

## 1. API 整体不可用

**现象：** 5xx 比例陡增 / `/readyz` 返回 503 / Pod CrashLoopBackOff

**定位：**

```bash
kubectl -n rhythmind get pods -l app=rhythmind-api
kubectl -n rhythmind describe pod <pod>
kubectl -n rhythmind logs <pod> --previous
```

**常见根因与处置：**

| 现象 | 根因 | 处置 |
|---|---|---|
| 启动日志含 `Production startup blocked by unsafe configuration` | Secret 缺失或退化为默认值 | 检查 `rhythmind-secrets`，重建后 `kubectl rollout restart` |
| 启动日志含 `model_primary_spec='mlx://...'` | MLX spec 进了容器 | 设置 `MODEL_PRIMARY_SPEC=ollama://...`，回滚到上一个 ImageTag |
| Alembic upgrade 报错 | 迁移与 DB 状态不一致 | 见 §4 |
| `readyz` 报 `db=fail` | DB 不可达或连接池打满 | 见 §2 |
| `readyz` 报 `redis=fail` | Redis 不可达 | 见 §3 |
| 全部 Pod OOMKilled | LLM 上下文过大或并发过高 | 临时调大 `resources.limits.memory`，并降低 HPA 上限 |

**回滚：** `kubectl -n rhythmind rollout undo deploy/rhythmind-api`

---

## 2. PostgreSQL 故障

**现象：** `/readyz` 报 `db=fail` 或日志大量 `asyncpg.exceptions.ConnectionDoesNotExistError`

**定位：**

```bash
# 数据库可达性
kubectl -n rhythmind exec deploy/rhythmind-api -- \
  python -c "import asyncpg, asyncio, os; asyncio.run(asyncpg.connect(os.environ['DATABASE_URL'].replace('postgresql+asyncpg','postgresql')).wait_closed())"

# 连接数
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE datname='rhythmind';"

# 慢查询
psql $DATABASE_URL -c "SELECT pid, now()-query_start AS dur, query FROM pg_stat_activity WHERE state='active' ORDER BY dur DESC LIMIT 10;"
```

**处置：**

1. 连接数打满 → 临时 `kubectl scale deploy/rhythmind-api --replicas=N`，长期调小 `PG_POOL_SIZE`
2. 主实例宕机 → 触发托管数据库 failover；改 `DATABASE_URL` 指向 standby 不是必须，托管服务会自动切换 endpoint
3. 索引缺失导致慢查询 → 在 staging 加索引并 `ANALYZE`，确认后线上 `CREATE INDEX CONCURRENTLY`

### 2.1 数据库恢复演练

每季度至少一次：

```bash
# 1. 在 staging 集群恢复昨日快照
restore-from-snapshot --source prod --target staging --date YYYY-MM-DD

# 2. 拿一组真实 user_id 跑回归
pytest tests/integration/test_recovery_smoke.py --db staging
```

---

## 3. Redis / LoopGuard 异常

**现象：** RehabAgent 被无限触发 / `/readyz` 报 `redis=fail`

**处置：**

```bash
# 看是否有冷却中
kubectl -n rhythmind exec deploy/rhythmind-redis -- redis-cli KEYS 'loop:*' | head

# 强制清掉某用户冷却
kubectl -n rhythmind exec deploy/rhythmind-redis -- redis-cli DEL "loop:USER_ID:rehab"

# Redis 持久化失效（AOF/RDB 异常）
kubectl -n rhythmind exec deploy/rhythmind-redis -- redis-cli LASTSAVE
```

LoopGuard 在 Redis 不可达时**降级为放行**（`is_cooling_down` 内部 try/except），所以 Redis 抖动不会阻断业务，但要警惕"放行后无环保护"的窗口期 —— Redis 恢复前应人工监控 RehabAgent 调用频次。

---

## 4. Alembic 迁移失败

**现象：** Pod 启动日志 `rhythmind.alembic_failed`，进程退出

**典型场景与处置：**

1. **迁移版本号冲突**（多人并行写迁移）
   ```bash
   alembic merge -m "merge heads" <rev1> <rev2>
   ```
2. **迁移在生产数据上失败**（如加 NOT NULL 但有 NULL 行）
   - 立即 `kubectl rollout undo` 回到旧镜像（旧代码兼容旧 schema）
   - 在 staging 数据上复现 → 改成两阶段：先加可空列 + 数据回填 → 再加约束
3. **多副本同时跑迁移**
   - 改成 K8s `initContainer` 单独跑一次：
     ```yaml
     initContainers:
       - name: migrate
         image: ghcr.io/your-org/rhythmind:0.1.5
         command: ["alembic", "upgrade", "head"]
         envFrom: [{ secretRef: { name: rhythmind-secrets } }]
     ```
   - 同时把 Deployment 的 `RUN_MIGRATIONS_ON_STARTUP=false`

---

## 5. LLM 推理异常

### 5.1 LiteLLM 上游 5xx

**现象：** Sentry 抓到 `litellm.APIError`，CoachAgent 输出空

**处置：**

```bash
# 看 LiteLLM 自身健康
curl http://litellm:4000/health

# 切换到备用模型（运行时无需改代码）
kubectl -n rhythmind set env deploy/rhythmind-api \
  MODEL_PRIMARY=fast              # deepseek-chat
```

### 5.2 Ollama 不可达

**现象：** PromptAuditor 日志大量 `OllamaAdapter timeout`

**降级：** PromptAuditor 设计上"超时即放行"，业务不会中断，但合规风险升高。临时 `COMPLIANCE_AUDIT_ENABLED=false` 关闭前置审查（仍保留后置 ComplianceGate）。

### 5.3 MLX OOM（仅 macOS 部署）

**现象：** `Metal: out of memory`

**处置：**
- 重启进程释放 GPU 内存
- 把 `MLX_MAX_TOKENS` 调小、`MLX_SEMAPHORE_LIMIT=1`（默认）
- 实在不行换 `ollama://qwen2.5:7b`

---

## 6. QMD 语义检索不可用

**现象：** Hermes 第 2 步 `retrieve_skills` 抛 `QMDUnavailableError`

**降级：** 业务不中断（HermesBase 设计上技能为"可选"）；监控指标 `hermes_skills_retrieved_total` 短期归零。

```bash
# QMD 重启
kubectl -n rhythmind rollout restart deploy/rhythmind-qmd

# 重建索引
kubectl -n rhythmind exec deploy/rhythmind-qmd -- qmd collection rebuild agent_skills
```

---

## 7. 合规告警

### 7.1 误拦截激增

**现象：** `compliance_blocked_total` 异常上升，用户反馈"问什么都不答"

**定位：**
1. Grafana 看 PromptAuditor 与 ComplianceGate 各自拦截比例
2. 抽样查 `audit_log` 表的最近 BLOCK 记录

**处置：**
- 短期：临时调高 `COMPLIANCE_AUDIT_BLOCK_SCORE`（默认 0.75 → 0.85）
- 长期：用 BLOCK 样本回填合规规则集合，更新 `data/compliance_rules`

### 7.2 漏拦截

> 任何疑似的"未拦截却应拦截"案例，都按 SECURITY.md §3 上报；优先级 P1。

---

## 8. 关键指标与告警阈值

| 指标 | 来源 | 阈值（建议） |
|---|---|---|
| HTTP 5xx 比例 | nginx / OTel | >1% 持续 5min → P2 |
| `/readyz` 503 | K8s Probe | 任何 1 个 Pod 持续 60s → P2 |
| LLM P95 延迟 | OTel histogram | > 30s 持续 10min → P3 |
| `compliance_blocked_total` 增速 | Prometheus | 较前 1h 涨 ≥ 3× → P3 |
| Pool 命中率 | 自定义 metric | < 50% 持续 30min → P4 |
| PG 连接数 | pg_exporter | > 80% pool 上限 → P3 |

> 上述指标需先按 P1 任务接通 OTel + Prometheus exporter 才能用。当前版本仅有 structlog 日志，需要短期内补齐。

---

## 9. 应急联系人

| 角色 | 联系方式 |
|---|---|
| 项目作者（一线 Oncall） | 14455975@qq.com |
| 数据库 DBA | TBD |
| 安全响应 | security@rhythmind.ai（SECURITY.md） |
