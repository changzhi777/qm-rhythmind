# rhythmind/core — Hermes 核心层

> `[根目录(../../CLAUDE.md) > **rhythmind** > **core**`

---

## 模块职责

Hermes Pattern v2 的核心实现，包含：

- **HermesBase**: 所有 Agent 的抽象基类（6 步执行循环）
- **MemoryManager**: 会话记忆管理
- **FactManager**: 健康知识图谱
- **SkillEngine**: 技能提取与复用
- **ComplianceGate / PromptAuditor**: 合规审查（双层防护）
- **QMDClient**: 本地语义搜索客户端

---

## 入口与启动

- **Agent 基类**: `from rhythmind.core.hermes_base import HermesBase`
- **记忆管理**: `from rhythmind.core.memory import MemoryManager, init_db`
- **QMD 客户端**: `from rhythmind.core.qmd import QMDClient`
- **合规**: `from rhythmind.core.compliance import PromptAuditor, ComplianceGate`

---

## 对外接口

### HermesBase (ABC)

```python
class HermesBase(ABC):
    def __init__(self, agent_name: str, user_id: str) -> None: ...
    async def run(self, ctx: AgentContext) -> HermesRunResult: ...
    async def execute(self, ctx, memory_ctx, skill_ctx) -> AgentResult: ...  # 抽象方法
    async def call_llm(self, messages, model, temperature, max_tokens, response_format) -> str: ...
    async def remember(self, key, value, mem_type) -> None: ...
    async def recall(self, query, top_k) -> list[dict]: ...
    async def search_knowledge(self, query, collection) -> list[dict]: ...

# 六步执行循环
# 1. retrieve_memory  — 从 MemoryManager 召回历史上下文
# 2. retrieve_skills  — 从 QMD agent_skills 检索相关技能
# 3. execute          — 子类实现具体业务逻辑（抽象方法）
#    └─ call_llm()   — [新增] 透明 prompt 审查：gemma-4-e4b 本地预检
# 4. compliance_check — ComplianceGate 三级输出分级
# 5. extract_skills + update_memory — 沉淀经验、更新记忆
```

### MemoryManager

```python
class MemoryManager:
    def __init__(self, user_id: str, agent: str) -> None: ...
    async def recall(self, task_type, mem_types, limit) -> MemoryRecallResult: ...
    async def write(self, key, value, mem_type, confidence, ttl_hours, tags) -> None: ...
    async def update(self, updates: dict) -> None: ...
    async def delete(self, key) -> None: ...
    async def purge_expired(self) -> int: ...
```

### FactManager

```python
class FactManager:
    def __init__(self, user_id: str) -> None: ...
    async def write_fact(self, subject, predicate, object_value, source, confidence, valid_from) -> HealthFact: ...
    async def write_fact_additive(self, ...) -> HealthFact: ...
    async def invalidate_fact(self, fact_id) -> bool: ...
    async def invalidate_by_subject(self, subject, predicate) -> int: ...
    async def query_current(self, subject, predicate) -> list[HealthFact]: ...
    async def query_history(self, subject, predicate, limit) -> list[HealthFact]: ...
    async def get_all_current(self) -> list[HealthFact]: ...
    async def get_current_goal(self) -> dict | None: ...
    async def get_current_injuries(self) -> list[dict]: ...
```

### QMDClient

```python
class QMDClient:
    def __init__(self, base_url, timeout) -> None: ...
    async def query(self, collection, query, user_ns, top_k, filters) -> list[dict]: ...
    async def upsert(self, collection, doc_id, content, metadata, user_ns) -> bool: ...
    async def index_skill(self, agent, skill_content, task_type) -> bool: ...
    async def index_user_memory(self, user_id, key, content) -> bool: ...
    async def query_user_memory(self, user_id, query, top_k) -> list[dict]: ...
```

### ComplianceGate

```python
class ComplianceGate:
    def __init__(self, rules) -> None: ...
    def validate(self, result, confidence_override) -> ComplianceResult: ...
    def pre_check(self, raw_input) -> bool: ...
```

### PromptAuditor

```python
class PromptAuditor:
    def __init__(self, model_spec) -> None: ...
    async def audit(self, messages) -> AuditResult: ...
```

---

## 关键依赖与配置

- **合规**: `ComplianceGate` + `PromptAuditor`（双层防护：前置 prompt 审查 + 后置输出分级）
- **QMD**: `qmd_url`, `qmd_timeout`, `qmd_top_k`
- **模型**: 通过 `AdapterRouter` 调用 LLM

---

## 数据模型

### AgentContext

```python
@dataclass
class AgentContext:
    user_id: str
    session_id: str
    task_type: str
    input_data: dict[str, Any]
    confidence_threshold: float = 0.75
    metadata: dict[str, Any] = field(default_factory=dict)
```

### AgentResult

```python
@dataclass
class AgentResult:
    output: Any
    confidence: float
    skill_candidates: list[str] = field(default_factory=list)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = False
```

### HermesRunResult

```python
@dataclass
class HermesRunResult:
    compliance: ComplianceResult
    agent: str
    user_id: str
    task_type: str
    latency_ms: float
    audit_result: AuditResult | None = None
    output: Any = field(init=False)
    success: bool = field(init=False)
```

### ComplianceResult

```python
@dataclass
class ComplianceResult:
    level: ComplianceLevel  # PASS / WARN / BLOCK
    output: Any             # BLOCK 时为 None
    confidence: float
    skill_candidates: list[str]
    memory_updates: dict[str, Any]
    requires_human_review: bool
    triggered_keywords: list[str]
    disclaimer_appended: bool
```

### AuditResult

```python
@dataclass
class AuditResult:
    level: AuditLevel
    overall_score: float
    medical_risk: float
    privacy_risk: float
    hallucination_risk: float
    reason: str
    extra_constraints: list[str]
    auditor_available: bool
```

### MemoryEntry / MemoryRecallResult

```python
class MemoryEntry(BaseModel):
    namespace: str
    key: str
    value: Any
    mem_type: MemoryType
    confidence: float
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    tags: list[str]

class MemoryRecallResult(BaseModel):
    entries: list[MemoryEntry]
    total: int
```

### HealthFact

```python
class HealthFact(Base):
    id: int
    user_id: str
    subject: str
    predicate: str
    object_json: Any
    source: str
    confidence: float
    valid_from: datetime
    valid_until: datetime | None
    created_at: datetime
    @property
    def is_current(self) -> bool: ...
```

---

## 测试与质量

- 测试目录：`tests/unit/` 下有 core 相关测试
- 代码风格：`ruff check src/rhythmind/core/`

---

## 常见问题 (FAQ)

**Q: Hermes Pattern 的六步循环是什么？**  
A: 1) recall_memory → 2) retrieve_skills → 3) execute (call_llm) → 4) compliance_check → 5) extract_skills → 6) update_memory

**Q: 合规审查失败会怎样？**  
A: 抛出 `ComplianceBlockedError`，由 `execute()` 捕获并返回降级 `AgentResult`，或上浮由 `run()` 统一处理。

**Q: QMD 不可用时是否影响主流程？**  
A: QMD 搜索失败时静默降级，不阻断 Agent 执行。

---

## 相关文件清单

```
src/rhythmind/core/
├── __init__.py
├── hermes_base.py          # Agent 基类（6 步循环）
├── memory/
│   ├── __init__.py        # 公开 API: MemoryManager, FactManager, HealthFact, MemoryEntry
│   ├── manager.py         # MemoryManager + init_db
│   ├── models.py          # AgentMemory, SkillRecord, HealthFact ORM 模型
│   ├── types.py           # MemoryEntry, MemoryRecallResult, MemoryType
│   └── fact_manager.py   # FactManager
├── skill/
│   ├── __init__.py
│   ├── engine.py          # SkillEngine
│   └── extractor.py       # SkillExtractor
├── compliance/
│   ├── __init__.py
│   ├── gate.py            # ComplianceGate（三级输出分级）
│   ├── prompt_auditor.py  # PromptAuditor（gemma 前置审查）
│   └── keywords.py        # 关键词规则加载
└── qmd/
    ├── __init__.py
    └── client.py          # QMDClient
```

---

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增所有子模块详细接口和数据模型
- **2026-05-12** 首次 AI 上下文初始化
