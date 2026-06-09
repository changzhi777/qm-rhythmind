# CLAUDE.md — scripts/ 运维脚本

> `[根目录(../CLAUDE.md) > **scripts**`

> **最后更新:** 2026-05-27T10:50:56+08:00

---

## 变更记录 (Changelog)

- **2026-05-27** 新增 `stress_test.py` 渐进式压力测试脚本
- **2026-05-27** 新增 `ingest_knowledge.py` 知识库入库脚本
- **2026-05-18** 首次 AI 上下文初始化

---

## 模块职责

开发、构建、部署、数据入库、性能测试相关的运维脚本集合。

---

## 脚本列表

### 数据入库

| 脚本 | 用途 |
|------|------|
| `run_ingestion.py` | 一键入库 + 仪表盘服务：读取 Garmin 数据 → 写入 DB → AI 分析 → 启动 FastAPI |
| `ingest_garmin_export.py` | Garmin Connect 导出包 CSV → 逐条推入 `/api/v1/health/upload`，跑通三阶段流水线 |
| `ingest_knowledge.py` | 知识库入库脚本：解析 `docs/knowledge/*.md` → 写入 `knowledge_article` + `knowledge_reference` 表 |

**run_ingestion.py 用法**：
```bash
python scripts/run_ingestion.py          # 入库 + 启动服务（默认 localhost:8088）
python scripts/run_ingestion.py --ingest # 仅入库
python scripts/run_ingestion.py --serve  # 仅启动服务
python scripts/run_ingestion.py --data-dir /path/to/garmin  # 指定数据目录
```

**ingest_garmin_export.py 用法**：
```bash
python scripts/ingest_garmin_export.py \
    --export-dir ~/Downloads/garmin_export \
    --base-url http://localhost:8000 \
    --token alice --limit 10
```

**ingest_knowledge.py 用法**：
```bash
python scripts/ingest_knowledge.py                          # 默认 SQLite: data/knowledge.db
python scripts/ingest_knowledge.py --db postgresql://...    # 指定 PostgreSQL
```

### 版本与发布

| 脚本 | 用途 |
|------|------|
| `bump_version.py` | 版本号自动升级（同步 VERSION + `_version.py` + `pyproject.toml`） |
| `release.sh` | 本地发布流程：测试 → bump → changelog → git tag → push |

**bump_version.py 用法**：
```bash
python scripts/bump_version.py patch   # 0.1.9 → 0.2.0
python scripts/bump_version.py minor   # 0.1.9 → 0.2.0
python scripts/bump_version.py major   # 0.1.9 → 1.0.0
```

### 性能测试

| 脚本 | 用途 |
|------|------|
| `stress_test.py` | 渐进式压力测试：3 层（轻量 API / Agent+LLM / 综合上传），9 阶段递增并发，生成 MD+HTML 报告 + 架构优化建议 |

**stress_test.py 用法**：
```bash
python3 scripts/stress_test.py   # 运行全量压测，报告输出到 /tmp/qm-stress-reports/
```

**测试分层**：
- Layer1: 轻量 API（/ping, /health, /version, /dashboard, /reports, /test-reports）— 5→200 并发
- Layer2: Agent+LLM（/qm/api/chat）— 3→10 并发
- Layer3: 综合上传（/api/v1/health/upload）— 3 并发

### 基础设施

| 脚本 | 用途 |
|------|------|
| `init_postgres.sql` | PostgreSQL 初始化（uuid-ossp / pg_trgm / pgcrypto 扩展） |
| `bootstrap_lock.sh` | 生成 poetry.lock（首次 clone 或依赖变更后） |
| `setup_secrets.sh` | 生产密钥配置 |
| `docker-entrypoint.sh` | Docker 容器入口脚本 |
| `init_qmd_collections.sh` | QMD 语义搜索初始化集合 |

---

## 环境依赖

- `run_ingestion.py` 需要 `rhythmind` 包已安装（`pip install -e .`）
- `stress_test.py` 依赖 `aiohttp`（独立异步脚本）
- `bump_version.py` 纯标准库
- `bootstrap_lock.sh` 需要 Poetry

- `ingest_knowledge.py` 依赖 SQLAlchemy（`rhythmind.db.knowledge_models`）
