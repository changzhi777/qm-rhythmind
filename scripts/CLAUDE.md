# CLAUDE.md — scripts/ 运维脚本

> `[根目录(../CLAUDE.md) > **scripts**`

---

## 模块职责

开发、构建、部署、数据入库相关的运维脚本集合。

---

## 脚本列表

### 数据入库

| 脚本 | 用途 |
|------|------|
| `run_ingestion.py` | 一键入库 + 仪表盘服务：读取 Garmin 数据 → 写入 DB → AI 分析 → 启动 FastAPI |
| `ingest_garmin_export.py` | Garmin Connect 导出包 CSV → 逐条推入 `/api/v1/health/upload`，跑通三阶段流水线 |

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
- `ingest_garmin_export.py` 仅依赖 `httpx`（独立脚本）
- `bump_version.py` 纯标准库
- `bootstrap_lock.sh` 需要 Poetry

---

## 变更记录 (Changelog)

- **2026-05-18** 首次 AI 上下文初始化
