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

### 2.1 S3 审计日志桶配置 <!-- FUTURE: 需要 AWS 账号配置 -->

> **⚠️ 待完成（TBD）** — 需要 AWS 访问权限才能完成此配置。
>
> S3JsonlSink 需要：
> 1. 创建 S3 bucket（启用 Object Lock Compliance 模式防篡改）
> 2. 配置 bucket policy 限制仅 rhythmind 实例写入
> 3. 在 `settings.s3_audit_bucket` 指定 bucket 名称
>
> 相关文件：`src/rhythmind/audit/sinks.py` 的 `S3JsonlSink`

**步骤：**

1. 在 AWS Console 或 CLI 创建 bucket：
   ```bash
   aws s3 mb s3://rhythmind-audit-logs --region us-east-1
   aws s3api put-object-lock-configuration \
     --bucket rhythmind-audit-logs \
     --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":30}}}'
   ```

2. 配置 IAM Policy（限制仅写入，不允许删除）：
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::rhythmind-audit-logs/*"
       }
     ]
   }
   ```

3. 设置环境变量：
   ```bash
   S3_AUDIT_BUCKET=rhythmind-audit-logs
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   ```

### 2.1 数据库恢复演练

#### 备份策略

| 备份类型 | 频率 | 保留时间 | 目标 RTO | 目标 RPO |
|----------|------|----------|----------|----------|
| 全量快照 | 每日 | 30 天 | < 4 小时 | < 24 小时 |
| WAL 归档 | 连续 | 7 天 | - | < 5 分钟 |
| 逻辑备份 (pg_dump) | 每周 | 12 周 | - | < 1 周 |

#### PITR 恢复步骤

> **注意：** 以下假设使用云托管 PostgreSQL（RDS/PolarDB）或带有 WAL 归档的自托管 PG。

**1. 准备工作**

```bash
# 确认 WAL 归档状态
psql $DATABASE_URL -c "SELECT * FROM pg_stat_archiver;"

# 确认最近快照时间
aws rds describe-db-snapshots --db-instance-identifier rhythmind-prod
```

**2. 恢复到指定时间点 (PITR)**

```bash
# 停止应用（避免写入）
kubectl -n rhythmind scale deployment rhythmind-api --replicas=0

# 执行 PITR 恢复（以 RDS 为例）
aws rds restore-db-instance-from-db-snapshot \
    --db-instance-identifier rhythmind-recovered \
    --db-snapshot-identifier <latest-snapshot> \
    --restore-time $(date -d "YYYY-MM-DD HH:MM:SS" -u '+%Y-%m-%dT%H:%M:%SZ')

# 等待恢复完成
aws rds wait db-instance-available --db-instance-identifier rhythmind-recovered

# 验证数据完整性
psql $RECOVERED_DB_URL -c "SELECT COUNT(*) FROM agent_memory;"
psql $RECOVERED_DB_URL -c "SELECT COUNT(*) FROM health_fact;"
```

**3. 恢复后验证**

```bash
# 启动应用（指向恢复的 DB）
kubectl set env deployment/rhythmind-api DATABASE_URL=$RECOVERED_DB_URL
kubectl -n rhythmind scale deployment rhythmind-api --replicas=1

# 跑回归测试
pytest tests/integration/test_recovery_smoke.py --db recovered

# 验证关键业务流程
pytest tests/integration/test_health_upload_e2e.py
pytest tests/integration/test_admin_skill_approval.py
```

**4. 清理**

```bash
# 恢复完成后删除临时实例
aws rds delete-db-instance --db-instance-identifier rhythmind-recovered --skip-final-snapshot
```

#### 季度演练检查清单

| 检查项 | 预期结果 | 实际结果 |
|--------|----------|----------|
| 快照恢复成功 | < 30 分钟 | |
| PITR 恢复到指定时间点 | 数据完整 | |
| 应用连接恢复的 DB 正常 | /readyz 返回 200 | |
| 回归测试全部通过 | 0 failed | |
| RTO 满足目标 | < 4 小时 | |
| RPO 满足目标 | < 24 小时 | |

**演练记录：**

| 日期 | 执行人 | 恢复耗时 | RTO | RPO | 发现问题 |
|------|--------|----------|-----|-----|----------|
| TBD | | | | | |

> **建议**：使用 AWS DMS 或 pgLogical 实现从 RDS 到 staging 的实时复制，每季度做一次真实恢复演练。

---

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

### 7.3 HIPAA/PIPL 法律审查 <!-- FUTURE: 需要法务团队 -->

> **⚠️ 待完成（TBD）** — HIPAA（美国）和 PIPL（中国）合规审查需要法务团队参与。
>
> 当前实现的功能：
> - 数据删除：`POST /api/v1/privacy/delete`（GDPR 覆盖）
> - 审计日志：`AuditEvent` + `S3JsonlSink`（待 S3 bucket 配置）
> - 合规规则：`data/compliance_rules/medical_keywords.yaml`
>
> 待法务审查：
> 1. 健康数据保留期限（HIPAA 要求 6 年，PIPL 各省不同）
> 2. 数据处理协议（DPA）需要与每个供应商签署
> 3. 用户同意书（consent form）是否符合当地法规
> 4. 数据泄露通报流程（72小时通报要求）
>
> 相关文件：`docs/SECURITY.md` §2.3

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

---

## 10. 密钥轮换流程

> **建议每 90 天执行一次密钥轮换。** 以下为标准化操作流程。

### 10.1 JWT_SECRET 轮换

JWT 密钥用于签署用户会话令牌。轮换期间需确保新旧令牌兼容。

**步骤：**

1. **生成新密钥**
   ```bash
   # 生成 32 字符以上的随机字符串
   NEW_JWT_SECRET=$(openssl rand -hex 32)
   echo "新 JWT_SECRET: $NEW_JWT_SECRET"
   ```

2. **更新 K8s Secret（滚动更新）**
   ```bash
   kubectl -n rhythmind create secret generic rhythmind-secrets \
       --from-literal=JWT_SECRET="$NEW_JWT_SECRET" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **触发滚动更新**
   ```bash
   kubectl -n rhythmind rollout restart deploy/rhythmind-api
   kubectl -n rhythmind rollout status deploy/rhythmind-api
   ```

4. **验证**
   - 检查 `/readyz` 返回 200
   - 确认新旧用户都能正常登录

**注意：** 轮换后旧 JWT 令牌立即失效，用户需重新登录。

### 10.2 LITELLM_MASTER_KEY 轮换

LiteLLM Proxy 的主密钥。

**步骤：**

1. **更新 LiteLLM Proxy 配置**
   ```bash
   # 在 LiteLLM Proxy 端更新密钥
   litellm --master_key <NEW_KEY>
   ```

2. **更新 K8s Secret**
   ```bash
   kubectl -n rhythmind create secret generic rhythmind-secrets \
       --from-literal=LITELLM_MASTER_KEY="$NEW_LITELLM_KEY" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **重启 API Pod**
   ```bash
   kubectl -n rhythmind rollout restart deploy/rhythmind-api
   ```

### 10.3 DATABASE_URL 凭证轮换

PostgreSQL 密码轮换。

**步骤：**

1. **在 PostgreSQL 端更新密码**
   ```sql
   ALTER USER rhythmind WITH PASSWORD 'new_strong_password';
   ```

2. **更新 K8s Secret**
   ```bash
   kubectl -n rhythmind create secret generic rhythmind-secrets \
       --from-literal=DATABASE_URL="postgresql+asyncpg://rhythmind:new_strong_password@<HOST>:5432/rhythmind?ssl=require" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **重启连接池**
   ```bash
   kubectl -n rhythmind rollout restart deploy/rhythmind-api
   ```

### 10.4 INFLUXDB_TOKEN 轮换

InfluxDB 2.x API Token 轮换。

**步骤：**

1. **在 InfluxDB 端生成新 Token**
   ```bash
   influx auth create \
       --org rhythmind \
       --description "rhythmind-api-$(date +%Y%m)" \
       --read-buckets \
       --write-buckets
   ```

2. **撤销旧 Token**
   ```bash
   influx auth delete --id <OLD_TOKEN_ID>
   ```

3. **更新 K8s Secret**
   ```bash
   kubectl -n rhythmind create secret generic rhythmind-secrets \
       --from-literal=INFLUXDB_TOKEN="$NEW_INFLUX_TOKEN" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```

4. **重启 Pod**
   ```bash
   kubectl -n rhythmind rollout restart deploy/rhythmind-api
   ```

### 10.5 Redis AUTH 密码轮换（如已启用 ACL）

**步骤：**

1. **更新 Redis 密码**
   ```bash
   kubectl -n rhythmind exec deploy/rhythmind-redis -- redis-cli CONFIG SET requirepass "new_redis_password"
   ```

2. **同步到所有 Pod**
   ```bash
   kubectl -n rhythmind create secret generic rhythmind-secrets \
       --from-literal=REDIS_URL="redis://:new_redis_password@localhost:6379" \
       --dry-run=client -o yaml | kubectl apply -f -
   ```

3. **重启**
   ```bash
   kubectl -n rhythmind rollout restart deploy/rhythmind-api deploy/rhythmind-redis
   ```

### 10.6 轮换日历提醒

| 密钥 | 轮换周期 | 上次轮换 | 下次轮换 | 负责人 |
|---|---|---|---|---|
| JWT_SECRET | 90 天 | TBD | TBD | Oncall |
| LITELLM_MASTER_KEY | 90 天 | TBD | TBD | Oncall |
| DATABASE_URL | 180 天 | TBD | TBD | DBA |
| INFLUXDB_TOKEN | 90 天 | TBD | TBD | Oncall |
| REDIS_AUTH | 180 天 | TBD | TBD | Oncall |

> **建议使用 Vault 或 AWS Secrets Manager 管理密钥生命周期，自动化轮换流程。**
