# CLAUDE.md — scripts/ 运维脚本

> `[根目录(../CLAUDE.md) > **scripts**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 变更记录 (Changelog)

- **2026-06-10** 新增 `run_qmd_server.py`（QMD 兼容服务）+ `ingest_claude_md.py`（项目上下文入库）
- **2026-06-10** 深化：补充所有脚本完整参数表、环境变量、退出码、Shell 脚本详情
- **2026-05-27** 新增 `stress_test.py` 渐进式压力测试脚本
- **2026-05-27** 新增 `ingest_knowledge.py` 知识库入库脚本
- **2026-05-18** 首次 AI 上下文初始化

---

## 模块职责

开发、构建、部署、数据入库、性能测试相关的运维脚本集合。共 11 个文件（6 Python + 5 Shell），总计 ~2082 行。

---

## 脚本总览

| 脚本 | 类型 | 行数 | 用途 | 依赖 |
|------|------|------|------|------|
| `stress_test.py` | Python | 596 | 渐进式压力测试 + 报告生成 | aiohttp |
| `ct109_smoke_test.py` | Python | 422 | CT109 部署冒烟测试 | requests, psycopg2 |
| `ingest_garmin_export.py` | Python | 343 | Garmin CSV 批量入库 | requests |
| `run_ingestion.py` | Python | 198 | 一键入库+仪表盘服务 | rhythmind 包 |
| `ingest_claude_md.py` | Python | 280 | 项目上下文 CLAUDE.md+Memory→DB+QMD | SQLAlchemy |
| `ingest_knowledge.py` | Python | 142 | 知识库 Markdown → DB | SQLAlchemy |
| `run_qmd_server.py` | Python | 265 | 轻量 QMD 兼容服务（@tobi/qmd替代） | uvicorn, starlette |
| `bump_version.py` | Python | 86 | 版本号自动升级 | 纯标准库 |
| `setup_secrets.sh` | Shell | 66 | 生产密钥配置 | — |
| `release.sh` | Shell | 94 | 测试→bump→tag→push | bump_version.py |
| `init_qmd_collections.sh` | Shell | 74 | QMD 语义搜索初始化 | — |
| `docker-entrypoint.sh` | Shell | 34 | Docker 容器入口 | — |
| `bootstrap_lock.sh` | Shell | 27 | 生成 poetry.lock | Poetry |
| `seed_test_account.py` | Python | 220 | 部署脱敏测试账户(张晨 → 张远舟) | rhythmind, sqlalchemy |

---

## 详细接口

### run_ingestion.py — 一键入库 + 仪表盘服务

```bash
python scripts/run_ingestion.py                          # 入库 → 服务（默认）
python scripts/run_ingestion.py --ingest                 # 仅入库
python scripts/run_ingestion.py --serve                  # 仪启动服务 (0.0.0.0:8088)
python scripts/run_ingestion.py --data-dir /path/to/data # 指定 Garmin 数据目录
python scripts/run_ingestion.py --ingest --data-dir ./export  # 仅入库指定目录
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--ingest` | flag | off | 仅执行数据入库 + AI 分析，不启动服务 |
| `--serve` | flag | off | 仅启动 FastAPI + 静态文件服务 |
| `--data-dir` | path | `data/garmin_export/` | Garmin Connect 导出数据目录 |

**环境变量（运行时自动设置默认值）：**

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `ENV` | `test` | 运行环境 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./garmin_health.db` | 数据库连接 |
| `REDIS_URL` | `redis://localhost:6379/15` | Redis 缓存 |
| `QMD_URL` | `http://localhost:8181` | QMD 语义搜索 |
| `DEV_AUTH_BYPASS` | `true` | 跳过认证 |
| `ENFORCE_MODEL_PLATFORM` | `false` | 不强制模型平台 |

**流程**: 初始化 DB → `GarminDataSourceAdapter` → `IngestionEngine.ingest()` → `IngestionEngine.analyze()` → FastAPI

**退出码**: `1` — 无数据目录或依赖缺失

---

### ingest_garmin_export.py — Garmin CSV 批量入库

```bash
python scripts/ingest_garmin_export.py \
    --export-dir ~/Downloads/garmin_export \
    --base-url http://localhost:8000 \
    --token alice \
    --limit 10
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--export-dir` | path | **必填** | Garmin Connect 导出 CSV 目录 |
| `--base-url` | url | `http://localhost:8000` | RHYTHMIND API 地址 |
| `--token` | string | **必填** | 认证 token（DEV_AUTH_BYPASS 时可用任意值） |
| `--limit` | int | 0 (全集) | 限制处理条目数 |

**数据流**: CSV 逐行解析 → `POST /api/v1/health/upload` → 三阶段 Swarm 流水线

---

### ingest_knowledge.py — 知识库入库

```bash
python scripts/ingest_knowledge.py                          # 默认 SQLite: data/knowledge.db
python scripts/ingest_knowledge.py --db postgresql://...     # 指定 PostgreSQL
python scripts/ingest_knowledge.py --domain osa              # 仅入库 OSA 领域
python scripts/ingest_knowledge.py --domain sleep            # 仅入库睡眠领域
python scripts/ingest_knowledge.py --domain vo2max           # 仅入库 VO2max 领域
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--db` | url | `sqlite:///data/knowledge.db` | 数据库连接 URL |
| `--domain` | string | 全量 | 领域筛选: `osa` / `sleep` / `vo2max` |

**数据源**: `docs/knowledge/*.md` → 解析 Markdown → `knowledge_article` + `knowledge_reference` 表

**退出码**: `0` 成功 / `1` 解析失败

---

### bump_version.py — 版本号自动升级

```bash
python scripts/bump_version.py          # 默认 patch
python scripts/bump_version.py patch    # 0.1.9 → 0.1.10
python scripts/bump_version.py minor    # 0.1.9 → 0.2.0
python scripts/bump_version.py major    # 0.1.9 → 1.0.0
```

| 参数 | 位置 | 说明 |
|------|------|------|
| `part` | argv[1] | `patch` (第3位+1) / `minor` (第2位+1,第3位归0) / `major` (第1位+1,其余归0) |

**同步文件**: `VERSION` → `src/rhythmind/_version.py` (regex: `__version__ = "X.Y.Z"`) → `pyproject.toml` (regex: `version = "X.Y.Z"`)

**退出码**: `0` 成功 / `1` 参数错误

**触发方式**: `.githooks/pre-commit` 每次 `git commit` 自动调用

---

### stress_test.py — 渐进式压力测试

```bash
python3 scripts/stress_test.py   # 全量压测 → 报告输出到 /tmp/qm-stress-reports/
```

**可配置常量（文件内修改）：**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `API_URL` | `http://localhost:8000` | 后端 API 地址 |
| `FRONTEND_URL` | `http://localhost:3000` | 前端地址 |
| `REPORT_DIR` | `/tmp/qm-stress-reports/` | 报告输出目录 |

**测试分层与阶段：**

| Layer | 目标 | 端点 | 阶段 | 并发范围 |
|-------|------|------|------|---------|
| 1: 轻量 | 纯 IO 无 LLM | `/ping`, `/health`, `/version`, `/dashboard`, `/reports`, `/test-reports` | 3 阶段 | 5 → 50 → 200 |
| 2: 中量 | Agent + LLM | `/qm/api/chat` | 3 阶段 | 3 → 5 → 10 |
| 3: 重量 | 上传 + Agent | `/api/v1/health/upload` | 1 阶段 | 3 |

**数据模型**: `RequestResult` (ok/status/elapsed/error/endpoint/layer) → `StageResult` (并发聚合) → `StressReport` (报告生成)

**产出**: MD + HTML 报告 + 架构优化建议（基于各层通过率）

---

### ct109_smoke_test.py — 部署冒烟测试

```bash
python3 scripts/ct109_smoke_test.py
```

**测试项目（6 类）：**
1. 容器运行状态（systemctl 检查 4 个 LXC）
2. PostgreSQL 连接 + 表数量
3. FastAPI 端点可达性
4. InfluxDB 健康检查
5. Redis 连接
6. NFS 挂载状态

---

### Shell 脚本详情

#### setup_secrets.sh (66 行)

生产密钥配置脚本，生成/更新以下密钥文件：
- `.env.production` — 数据库密码、JWT_SECRET、API keys
- 检查已有密钥 → 跳过或覆盖

#### release.sh (94 行)

```bash
bash scripts/release.sh patch    # patch 版本发布
bash scripts/release.sh minor    # minor 版本发布
```

流程: `ruff check` → `pytest` → `bump_version.py` → `git add` → `git commit` → `git tag` → `git push --tags`

#### init_qmd_collections.sh (74 行)

QMD (Queryable Memory Database) 语义搜索初始化：
- 创建 collections（事实/会话/技能）
- 配置向量索引
- 依赖: QMD 服务已启动 (`QMD_URL`)

#### docker-entrypoint.sh (34 行)

Docker 容器入口：
1. 等待 PostgreSQL 可用
2. `alembic upgrade head`
3. `uvicorn rhythmind.api.main:app --host 0.0.0.0 --port 8000`

#### bootstrap_lock.sh (27 行)

```bash
bash scripts/bootstrap_lock.sh   # 生成 poetry.lock
```

---

## 环境依赖矩阵

| 脚本 | Python | 外部包 | 外部服务 | 文件系统 |
|------|--------|--------|---------|---------|
| `run_ingestion.py` | 3.12+ | rhythmind | PG/Redis/QMD (可选) | `data/garmin_export/` |
| `ingest_garmin_export.py` | 3.10+ | requests | RHYTHMIND API | CSV 导出目录 |
| `ingest_knowledge.py` | 3.12+ | SQLAlchemy | — | `docs/knowledge/*.md` |
| `stress_test.py` | 3.10+ | aiohttp | RHYTHMIND API + 前端 | `/tmp/qm-stress-reports/` |
| `ct109_smoke_test.py` | 3.10+ | requests, psycopg2 | CT109 全部服务 | — |
| `bump_version.py` | 3.10+ | — | — | `VERSION`, `pyproject.toml` |
| `setup_secrets.sh` | — | — | — | `.env.production` |
| `release.sh` | — | ruff, pytest | — | — |
| `init_qmd_collections.sh` | — | — | QMD API | — |
| `docker-entrypoint.sh` | — | alembic, uvicorn | PostgreSQL | — |
| `bootstrap_lock.sh` | — | Poetry | — | — |

---

## 输入输出路径总览

| 脚本 | 输入 | 输出 |
|------|------|------|
| `run_ingestion.py` | `data/garmin_export/` CSV/JSON | `garmin_health.db`, AI 报告, Dashboard 服务 |
| `ingest_garmin_export.py` | Garmin CSV 文件 | HTTP → DB (HealthFact 表) |
| `ingest_knowledge.py` | `docs/knowledge/*.md` | `knowledge_article` + `knowledge_reference` 表 |
| `stress_test.py` | — | `/tmp/qm-stress-reports/report-{ts}/` (MD + HTML) |
| `ct109_smoke_test.py` | — | stdout (通过/失败摘要) |
| `bump_version.py` | `VERSION` | 更新 VERSION + `_version.py` + `pyproject.toml` |
| `setup_secrets.sh` | — | `.env.production` |
| `release.sh` | — | git tag + push |
| `init_qmd_collections.sh` | — | QMD collections |
| `docker-entrypoint.sh` | — | uvicorn 进程 |
| `bootstrap_lock.sh` | `pyproject.toml` | `poetry.lock` |
