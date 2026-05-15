# rhythmind/db — 数据库层

> `[根目录(../../CLAUDE.md) > **rhythmind** > **db**`

---

## 模块职责

SQLAlchemy 异步模型定义 + Alembic 迁移管理，支持 SQLite（开发）和 PostgreSQL（生产）。

---

## 入口与启动

- **模型入口**: `from rhythmind.db.models import *`
- **初始化**: `from rhythmind.core.memory import init_db`（兜底建表）
- **迁移**: `alembic upgrade head`（生产通过 `run_migrations_on_startup=True` 自动执行）

---

## 对外接口

### 主要模型

| 模型 | 用途 |
|------|------|
| `AgentMemory` | 核心记忆表（namespace 隔离） |
| `SkillRecord` | 技能记录表（提取后存储） |
| `HealthFact` | 健康时序知识图谱 |

### Session 管理

```python
from rhythmind.core.memory.manager import AsyncSessionLocal

async with AsyncSessionLocal() as session:
    await session.execute(text("SELECT 1"))
```

---

## 关键依赖与配置

- **数据库驱动**: `aiosqlite` (dev), `asyncpg` (prod)
- **ORM**: `sqlalchemy[asyncio]`
- **迁移**: `alembic`
- **配置**: `settings.database_url`, `pg_pool_size`, `pg_pool_max_overflow`, `pg_pool_timeout`, `pg_pool_recycle`

---

## 数据模型

### AgentMemory

```python
class AgentMemory(Base):
    __tablename__ = "agent_memory"
    id: int
    namespace: str          # "user.{user_id}.{agent}.{key}"
    user_id: str
    agent: str
    key: str
    value_json: Any         # JSONB in PG, JSONText in SQLite
    tags: Any               # JSONB array
    mem_type: str           # user/feedback/project/reference
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    deleted_at: datetime | None
```

### SkillRecord

```python
class SkillRecord(Base):
    __tablename__ = "skill_record"
    id: int
    agent: str
    skill_hash: str
    content: str
    source_task: str
    confidence: float
    use_count: int
    status: str            # approved/pending/rejected
    created_at: datetime
    synced_to_qmd: bool
```

### HealthFact

```python
class HealthFact(Base):
    __tablename__ = "health_fact"
    id: int
    user_id: str
    subject: str           # user_goal / injury / baseline
    predicate: str         # targets / restricts / heart_rate_avg
    object_json: Any       # JSONB
    source: str
    confidence: float
    valid_from: datetime   # 生效时间
    valid_until: datetime | None  # NULL = 当前有效
    created_at: datetime
```

---

## 测试与质量

- 测试配置: `sqlite+aiosqlite:///:memory:` 用于单元测试覆盖
- 代码风格：`ruff check src/rhythmind/db/`

---

## 常见问题 (FAQ)

**Q: 开发环境使用什么数据库？**  
A: SQLite（通过 `aiosqlite`），通过 `DATABASE_URL` 环境变量切换。

**Q: 如何执行数据库迁移？**  
A: `alembic upgrade head`；容器化部署时可设置 `RUN_MIGRATIONS_ON_STARTUP=True` 自动执行。

**Q: migrations/versions/ 目录在哪里？**  
A: 位于 `db/migrations/versions/`（Alembic 标准结构）。

---

## 相关文件清单

```
src/rhythmind/db/
├── __init__.py
├── models.py          # SQLAlchemy ORM 模型定义
└── migrations/       # Alembic 迁移脚本
    ├── env.py
    └── versions/
        ├── 001_initial_schema.py   # 建表: agent_memory, skill_record
        ├── 002_health_fact.py      # 建表: health_fact (时序知识图谱)
        └── 003_skill_status.py     # skill_record 增加 status 列
```

## 迁移脚本详情

### 001_initial_schema
- **Revision ID**: 001_initial
- **建表**: `agent_memory`, `skill_record`
- **索引**: `(namespace, key)` UNIQUE, `(user_id, agent)`, GIN(value_json)
- **触发器**: `trg_agent_memory_updated_at` 自动更新 updated_at

### 002_health_fact
- **Revision ID**: 002_health_fact
- **建表**: `health_fact` (时序知识图谱)
- **设计**: valid_until NULL = 当前有效，非空 = 已过期保留历史
- **索引**: `(user_id, subject, predicate)`, `(user_id, valid_from)`, GIN(object_json)

### 003_skill_status
- **Revision ID**: 003_skill_status
- **变更**: `skill_record` 表增加 `status` 列 (approved/pending/rejected)
- **默认值**: `server_default='approved'` 向后兼容
- **索引**: `ix_skill_status`

---

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增完整数据模型
- **2026-05-12** 首次 AI 上下文初始化
