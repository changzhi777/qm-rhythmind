# rhythmind/db — 数据库层

> `[根目录](../../CLAUDE.md) > **rhythmind** > **db**`

---

## 模块职责

SQLAlchemy 异步模型定义 + Alembic 迁移管理，支持 SQLite（开发）和 PostgreSQL（生产）。包含健康管理核心表和医疗数据表。

---

## 入口与启动

- **模型入口**: `from rhythmind.db.models import *`（核心模型）, `from rhythmind.db.medical_models import *`（医疗模型）, `from rhythmind.db.knowledge_models import *`（知识库模型）
- **初始化**: `from rhythmind.core.memory import init_db`（兜底建表）
- **迁移**: `alembic upgrade head`（生产通过 `run_migrations_on_startup=True` 自动执行）

---

## 对外接口

### 核心模型（models.py）

| 模型 | 用途 |
|------|------|
| `AgentMemory` | 核心记忆表（namespace 隔离） |
| `SkillRecord` | 技能记录表（提取后存储） |
| `HealthFact` | 健康时序知识图谱 |

### 医疗模型（medical_models.py）

| 模型 | 用途 |
|------|------|
| `MedPatientProfile` | 患者画像（脱敏：gender, birth_year, blood_type, insurance_type） |
| `MedDiagnosis` | 诊断记录（diagnosis_name, icd_code, hospital, is_active） |
| `MedClinicalEvent` | 统一事件时间线（event_type: 入院/出院/手术/复诊/购药/化验） |
| `MedLabResult` | 化验结果（value, ref_range, flag, specimen） |
| `MedMedication` | 用药记录（medication_name, dose, route, frequency, status） |

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

### MedPatientProfile

```python
class MedPatientProfile(Base):
    __tablename__ = "med_patient_profile"
    id: int
    user_id: str           # unique
    name_hash: str         # 脱敏
    gender: str
    birth_year: int | None
    blood_type: str | None
    insurance_type: str | None
    demographics: Any      # JSONB
    created_at, updated_at: datetime
```

### MedDiagnosis

```python
class MedDiagnosis(Base):
    __tablename__ = "med_diagnosis"
    id: int
    user_id: str
    diagnosis_date: date
    diagnosis_name: str
    diagnosis_type: str
    icd_code: str | None
    hospital: str | None
    is_active: bool        # default=True
    metadata_: Any         # JSONB
    created_at: datetime
    # 索引: (user_id, diagnosis_date), (user_id, is_active)
```

### MedClinicalEvent

```python
class MedClinicalEvent(Base):
    __tablename__ = "med_clinical_event"
    id: int
    user_id: str
    event_date: datetime
    event_type: str        # 入院/出院/手术/复诊/购药/化验
    hospital, department: str | None
    duration_days: int | None
    cost: float | None
    details: Any           # JSONB
    created_at: datetime
    # 索引: (user_id, event_date), (user_id, event_type)
```

### MedLabResult

```python
class MedLabResult(Base):
    __tablename__ = "med_lab_result"
    id: int
    user_id: str
    test_date: datetime
    test_name: str
    value: float | None
    value_str: str | None
    unit: str | None
    ref_range: str | None
    flag: str | None       # H/L/HH/LL 等
    specimen: str | None
    metadata_: Any         # JSONB
    created_at: datetime
    # 索引: (user_id, test_name, test_date), (user_id, test_date)
```

### MedMedication

```python
class MedMedication(Base):
    __tablename__ = "med_medication"
    id: int
    user_id: str
    medication_name: str
    dose: str | None
    route: str | None
    frequency: str | None
    purpose: str | None
    start_date: date
    end_date: date | None
    status: str            # active/discontinued
    prescriber: str | None
    metadata_: Any         # JSONB
    created_at, updated_at: datetime
    # 索引: (user_id, status), (user_id, medication_name)
```

---

## 测试与质量

- 测试配置: `sqlite+aiosqlite:///:memory:` 用于单元测试覆盖
- 代码风格：`ruff check src/rhythmind/db/`
- **医疗模型测试**: `tests/unit/test_medical_models.py`（18 个测试）

---

## 常见问题 (FAQ)

**Q: 开发环境使用什么数据库？**
A: SQLite（通过 `aiosqlite`），通过 `DATABASE_URL` 环境变量切换。

**Q: 如何执行数据库迁移？**
A: `alembic upgrade head`；容器化部署时可设置 `RUN_MIGRATIONS_ON_STARTUP=True` 自动执行。

**Q: migrations/versions/ 目录在哪里？**
A: 位于 `db/migrations/versions/`（Alembic 标准结构）。

---

### KnowledgeArticle

```python
class KnowledgeArticle(Base):
    __tablename__ = "knowledge_article"
    id: int
    domain: str            # 领域分类: osa / sleep_performance / vo2max_training
    title: str             # 文章标题
    summary: str           # 摘要 (≤2048)
    content: Any           # JSONB 结构化正文 {sections: [{heading, body, key_points}]}
    source: str            # 来源: 论文标题/指南名称/网站
    source_type: str       # 来源类型: academic / clinical_guideline / web / textbook
    source_url: str | None
    published_date: str | None
    tags: Any              # JSONB array: ['osa', 'spo2', 'screening']
    relevance_score: float  # 关联度 0-1
    created_at: datetime
    references: list[KnowledgeReference]  # 关联引用
    # 索引: ix_ka_domain, ix_ka_source_type
```

### KnowledgeReference

```python
class KnowledgeReference(Base):
    __tablename__ = "knowledge_reference"
    id: int
    article_id: int        # FK → knowledge_article.id (CASCADE)
    ref_type: str          # citation / guideline / clinical_trial / meta_analysis
    ref_title: str
    ref_url: str | None
    ref_authors: str | None
    ref_year: int | None
    ref_journal: str | None
    ref_doi: str | None
    key_findings: Any      # JSONB {finding, evidence_level}
    created_at: datetime
    # 索引: ix_kr_article_id, ix_kr_ref_type
```

---

## 相关文件清单

```
src/rhythmind/db/
├── __init__.py
├── models.py            # SQLAlchemy ORM 核心模型（AgentMemory, SkillRecord, HealthFact）
├── medical_models.py    # 医疗 ORM 模型（5 张 med_* 表）
├── knowledge_models.py  # 知识库 ORM 模型（knowledge_article, knowledge_reference）
└── migrations/          # Alembic 迁移脚本
    ├── env.py
    └── versions/
        ├── 001_initial_schema.py          # 建表: agent_memory, skill_record
        ├── 002_health_fact.py             # 建表: health_fact (时序知识图谱)
        ├── 003_skill_status.py            # skill_record 增加 status 列
        ├── 004_audit_session_tables.py    # 建表: audit_log, user_session
        ├── 005_medical_tables.py          # 建表: med_patient_profile ~ med_medication
        └── 006_knowledge_tables.py        # 建表: knowledge_article, knowledge_reference
```

## 迁移脚本详情

### 001_initial_schema
- **Revision ID**: 001_initial
- **建表**: `agent_memory`, `skill_record`
- **索引**: `(namespace, key)` UNIQUE, `(user_id, agent)`, GIN(value_json)
- **触发器**: `trg_agent_memory_updated_at` 自动更新 updated_at
- **注意**: JSONB server_default 使用 `sa.text("'{}'::jsonb")` 以兼容 asyncpg

### 002_health_fact
- **Revision ID**: 002_health_fact
- **建表**: `health_fact` (时序知识图谱)
- **设计**: valid_until NULL = 当前有效，非空 = 已过期保留历史
- **索引**: `(user_id, subject, predicate)`, `(user_id, valid_from)`, GIN(object_json)
- **注意**: JSONB server_default 使用 `sa.text("'{}'::jsonb")`

### 003_skill_status
- **Revision ID**: 003_skill_status
- **变更**: `skill_record` 表增加 `status` 列 (approved/pending/rejected)
- **默认值**: `server_default='approved'` 向后兼容
- **索引**: `ix_skill_status`

### 004_audit_session_tables
- **Revision ID**: 004_audit_session_tables
- **建表**: `audit_log`（运营审计日志，防篡改 PG 持久化）, `user_session`（用户会话表）
- **索引**: `(user_id, created_at)`, `(event, created_at)` on audit_log
- **触发器**: `update_updated_at_column()` PostgreSQL 函数

### 005_medical_tables
- **Revision ID**: 005_medical_tables
- **建表**: `med_patient_profile`, `med_diagnosis`, `med_clinical_event`, `med_lab_result`, `med_medication`
- **设计**: 所有 JSONB 字段使用 `'{}'::jsonb` server_default（asyncpg 兼容）
- **索引**: 每张表 2-3 个复合索引

### 006_knowledge_tables
- **Revision ID**: 006_knowledge_tables
- **建表**: `knowledge_article`（领域知识条目）, `knowledge_reference`（文献引用）
- **设计**: article→reference 一对多，CASCADE 删除；JSONB content/tags/key_findings
- **索引**: `ix_ka_domain`, `ix_ka_source_type`, `ix_kr_article_id`, `ix_kr_ref_type`
- **数据源**: `docs/knowledge/*.md` 通过 `scripts/ingest_knowledge.py` 入库

---

## 变更记录 (Changelog)

- **2026-06-09** 增量更新：新增 knowledge_models.py（2 张知识库表）+ migration 006 + ingest_knowledge.py
- **2026-05-21** 新增 migration 005（医疗 5 表）+ medical_models.py
- **2026-05-18** 增量更新：新增 migration 004（audit_log + user_session 表）
- **2026-05-12** 完整扫描完成，新增完整数据模型
- **2026-05-12** 首次 AI 上下文初始化
