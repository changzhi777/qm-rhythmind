# RHYTHMIND 律动 — 部署指南（DEPLOYMENT.md）

> 适用版本：0.1.5+
> 维护者：外星动物（常智）/ IoTchange · 14455975@qq.com

本文涵盖三种部署形态：本地开发（docker compose）、单机生产（Docker）、K8s 生产（Helm 雏形）。

---

## 0. 前置准备

### 0.1 必备组件

| 组件 | 版本 | 角色 |
|---|---|---|
| Python | 3.12+ | 应用运行时 |
| PostgreSQL | 16 | 主存储（Hermes Memory、Skills、Facts） |
| Redis | 7 / Redis-Stack | LoopGuard、会话缓存 |
| InfluxDB | 2.7 | 可穿戴时序数据（可选） |
| LiteLLM Proxy | latest | 云端模型网关（Anthropic / DeepSeek） |
| Ollama | 最新 | 本地模型（合规审查 / 廉价兜底） |
| QMD | 最新 | 本地语义检索（Skills、Compliance Rules） |

主推理模型有两套部署形态：

- **Apple Silicon 本地：** `MODEL_PRIMARY_SPEC=mlx://mlx-community/Qwen3-30B-A3B-4bit`
- **服务器/容器：** `MODEL_PRIMARY_SPEC=ollama://qwen2.5:7b` 或 LiteLLM 别名 `primary`

容器化部署不支持 MLX；`config.py.assert_production_safe` 会在启动时拒绝。

### 0.2 必填环境变量

任何生产部署都至少要设置以下变量；不满足时容器入口脚本和 `assert_production_safe()` 会主动 fail-fast。

```bash
ENV=prod
JWT_SECRET=$(openssl rand -hex 32)              # ≥32 字符
LITELLM_MASTER_KEY=sk-<random>                  # 不能是 sk-1234 / sk-test
DATABASE_URL=postgresql+asyncpg://USER:PWD@HOST:5432/rhythmind   # 不可包含 rhythmind:rhythmind
INFLUXDB_TOKEN=<random>
MODEL_PRIMARY_SPEC=ollama://qwen2.5:7b          # 容器化必须避开 mlx://
CORS_ALLOW_ORIGINS=https://app.rhythmind.ai
RUN_MIGRATIONS_ON_STARTUP=true
DEV_AUTH_BYPASS=false                           # 生产强制 false
```

---

### 0.3 首次构建：生成 poetry.lock

`Dockerfile` 强依赖 `poetry.lock` 以保证镜像可重复构建。仓库**首次 clone 后**或
**任何时候 `pyproject.toml` 增改依赖后**，需要在本地执行：

```bash
bash scripts/bootstrap_lock.sh   # 等价 poetry lock --no-update --without cv
git add poetry.lock
git commit -m "chore: refresh poetry.lock"
```

CI 中的 `poetry-lock-check` job 会校验 lock 与 pyproject 一致；不一致即 fail。
若 PR 中没有改动依赖却提示不同步，多半是 `pyproject.toml` 被旁路修改 —— 重跑一次 `bootstrap_lock.sh` 即可。

> 不要把 `poetry.lock` 加入 `.gitignore`。

---

## 1. 本地开发（docker compose）

```bash
cp .env.example .env
# 必填字段：
#   JWT_SECRET=$(openssl rand -hex 32)
#   LITELLM_MASTER_KEY=sk-$(openssl rand -hex 16)
#   ANTHROPIC_API_KEY=...    # 若不调用云端可留空
docker compose up -d
docker compose logs -f api
```

启动后：

- API 文档：<http://localhost:8000/docs>
- 健康探针：`curl http://localhost:8000/livez`、`/readyz`
- Redis Insight：<http://localhost:8001>
- InfluxDB UI：<http://localhost:8086>

热重载已挂载源码目录，修改 `src/` 会自动 reload。

---

## 2. 单机生产（Docker）

```bash
# 1. 构建镜像
docker build -t rhythmind:0.1.5 .

# 2. 运行
docker run -d \
  --name rhythmind \
  -p 8000:8000 \
  --env-file /etc/rhythmind/prod.env \
  --restart=unless-stopped \
  rhythmind:0.1.5

# 3. 验证
curl https://your-host/livez
curl https://your-host/readyz   # 应返回 {"status":"ready",...}
```

数据库与 Redis 建议托管在外部（RDS/ElastiCache/阿里云 PolarDB 等），不要和 API 跑在同一台机器。

---

## 3. K8s 生产部署

> 仓库尚未提供完整 Helm chart，下面给出最小 Deployment 模板，可作为 chart 起点。

### 3.1 Secret

```bash
kubectl create secret generic rhythmind-secrets \
  --from-literal=JWT_SECRET=$(openssl rand -hex 32) \
  --from-literal=LITELLM_MASTER_KEY=$(openssl rand -hex 16) \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=DEEPSEEK_API_KEY=sk-... \
  --from-literal=INFLUXDB_TOKEN=$(openssl rand -hex 24) \
  --from-literal=DATABASE_URL=postgresql+asyncpg://rhythmind:STRONG_PWD@pg.rds:5432/rhythmind
```

### 3.2 Deployment（节选）

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rhythmind-api
spec:
  replicas: 2
  selector:
    matchLabels: { app: rhythmind-api }
  template:
    metadata:
      labels: { app: rhythmind-api }
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        seccompProfile: { type: RuntimeDefault }
      containers:
        - name: api
          image: ghcr.io/your-org/rhythmind:0.1.5
          ports: [{ containerPort: 8000 }]
          envFrom:
            - secretRef: { name: rhythmind-secrets }
          env:
            - { name: ENV, value: prod }
            - { name: RUN_MIGRATIONS_ON_STARTUP, value: "true" }
            - { name: CORS_ALLOW_ORIGINS, value: "https://app.rhythmind.ai" }
            - { name: MODEL_PRIMARY_SPEC, value: "ollama://qwen2.5:7b" }
            - { name: REDIS_URL, value: "redis://rhythmind-redis:6379" }
            - { name: SENTRY_DSN, valueFrom: { secretKeyRef: { name: rhythmind-secrets, key: SENTRY_DSN, optional: true } } }
          livenessProbe:
            httpGet: { path: /livez, port: 8000 }
            initialDelaySeconds: 20
            periodSeconds: 15
          readinessProbe:
            httpGet: { path: /readyz, port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 3
          resources:
            requests: { cpu: "500m", memory: "1Gi" }
            limits:   { cpu: "2",    memory: "4Gi" }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: ["ALL"] }
```

### 3.3 推荐配套资源

- **HPA：** `targetCPU=70%`，min=2，max=10。LLM 调用放大效应明显，建议同时按 RPS（自定义指标）扩。
- **PodDisruptionBudget：** `minAvailable: 1`
- **NetworkPolicy：** 仅允许 ingress controller、Redis、PG、LiteLLM、QMD、Ollama
- **Ingress / WAF：** 强制 HTTPS、HSTS、CSP；对 `/health/upload` 走 IP+token 双层限速
- **Backup：** PG 每日 base + WAL，至少 7 天保留；定期演练恢复（详见 RUNBOOK §3）

---

## 4. 数据库迁移流程

1. 本地编辑 ORM 模型（`src/rhythmind/core/memory/models.py`）
2. 生成迁移：`alembic revision --autogenerate -m "add_xxx"`
3. 人工审阅 `src/rhythmind/db/migrations/versions/<rev>.py`，特别注意 NOT NULL、UNIQUE、外键
4. 本地验证：`alembic upgrade head` → `pytest`
5. 提 PR，CI 通过后合并
6. 部署时：容器入口在 `RUN_MIGRATIONS_ON_STARTUP=true` 下自动 `alembic upgrade head`；多副本部署需用 `initContainer` 单独跑迁移，避免并发冲突

**重大变更（删表/改列）：** 走两阶段部署 —— 先部署"双写"代码 → 数据回填 → 删除旧列。

---

## 5. 发布流程

仓库已有 `.github/workflows/release.yml`：

```bash
python scripts/bump_version.py minor
git push
git tag v0.2.0
git push origin v0.2.0      # 触发 release.yml
```

CI 会构建 Docker 镜像并推到容器仓库，更新 CHANGELOG。

---

## 6. 部署核对清单（Go-Live Checklist）

- [ ] JWT_SECRET 长度 ≥ 32，且不在默认黑名单
- [ ] DEV_AUTH_BYPASS=false
- [ ] CORS_ALLOW_ORIGINS 显式枚举生产域名
- [ ] DATABASE_URL 不包含 `rhythmind:rhythmind`
- [ ] MODEL_PRIMARY_SPEC 在容器中不是 `mlx://`
- [ ] `/readyz` 返回 200 + `db=ok` + `redis=ok`
- [ ] `/docs` 与 `/redoc` 在生产已被关闭（`env=prod` 自动）
- [ ] Sentry DSN 配置且能在 Sentry UI 看到测试事件
- [ ] PG 备份每日运行且最近 24h 内有成功记录
- [ ] PodDisruptionBudget、HPA、NetworkPolicy 已就位
- [ ] Loop Guard、限流（待补）阈值与生产容量匹配
- [ ] RUNBOOK.md 中的常见故障演练过至少一次
