# rhythmind/audit — 审计日志

> `[根目录(../../CLAUDE.md) > **rhythmind** > **audit**`

---

## 模块职责

防篡改运营审计日志（对应威胁模型 R-3），支持多种 sink 实现的 fire-and-forget 异步日志。

---

## 入口与启动

- **入口**: `from rhythmind.audit import audit_log, AuditEvent, install_audit_sink`
- **初始化**: `install_audit_sink(sink)` 替换默认 sink
- **API 挂载**: `audit_router` 在 `api/main.py` 中

---

## 对外接口

### audit_log

```python
def audit_log(event: AuditEvent, **fields) -> None: ...
# 同步 + 异步通用入口，失败静默降级
```

### AuditEvent (枚举)

```python
class AuditEvent(StrEnum):
    PRIVACY_EXPORT = "privacy.export"
    PRIVACY_DELETE = "privacy.delete"
    PRIVACY_DELETE_FAILURE = "privacy.delete_failure"
    AUTH_BYPASS_USED = "auth.bypass_used"
    MCP_UNAUTHENTICATED = "mcp.unauthenticated"
    CONFIG_UNSAFE_STARTUP = "config.unsafe_startup"
    RATE_LIMIT_BLOCKED = "rate_limit.blocked"
    MODEL_SPEC_CHANGED = "model.spec_changed"
    SKILL_APPROVED = "skill.approved"
    SKILL_REJECTED = "skill.rejected"
```

### Sink 接口

```python
class AuditSink(ABC):
    @abstractmethod
    def emit(self, record: AuditRecord) -> None: ...

# 可用实现：
# - InMemorySink      # 测试用
# - StructlogSink     # 默认，生产降级
# - S3JsonlSink       # 生产 S3/SIEM（需 boto3）
# - PGSink            # PostgreSQL 持久化（配合 migration 004）
```

### install_audit_sink / get_sink

```python
def install_audit_sink(sink: AuditSink) -> None: ...
def get_sink() -> AuditSink: ...
```

---

### PGSink

```python
class PGSink(AuditSink):
    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0) -> None: ...
    def emit(self, record: AuditRecord) -> None: ...
    # 异步批量写入 audit_log 表，失败降级到 stderr
    # 需要 migration 004 创建 audit_log 表
```

---

## 关键依赖与配置

- **日志**: `structlog`
- **存储**: S3（生产）、PG（持久化）、内存（测试）、structlog（降级）
- **配置**: `settings.env`（决定默认 sink）

---

## 数据模型

### AuditRecord

```python
@dataclass
class AuditRecord:
    event: str
    user_id: str | None = None
    timestamp: float = field(default_factory=time.time)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    fields: dict[str, Any] = field(default_factory=dict)
```

日志记录格式：
```python
{
    "event": str,           # AuditEvent 值
    "timestamp": float,     # Unix timestamp
    "user_id": str | None,
    **fields               # 额外字段
}
```

**约束**: 永不持久化 PII 原值（health_rate/steps 等具体数值），只记 user_id + 操作元信息。

---

## 测试与质量

- 测试目录：`tests/` 下有 audit 相关测试
- 代码风格：`ruff check src/rhythmind/audit/`

---

## 常见问题 (FAQ)

**Q: 审计日志失败会影响业务吗？**  
A: 不会，失败走静默降级（fallthrough 到 structlog），不阻断业务。

**Q: 如何配置生产 audit sink？**  
A: 调用 `install_audit_sink(S3JsonlSink(...))`，替换默认的 StructlogSink。

**Q: S3JsonlSink 的不可篡改如何实现？**  
A: 需要 S3 桶启用 Object Lock（Compliance 模式）。

---

## 相关文件清单

```
src/rhythmind/audit/
├── __init__.py     # 公开 API: audit_log, AuditEvent, install_audit_sink, get_sink
├── events.py       # AuditEvent 枚举常量
├── logger.py      # 主日志入口 + install_audit_sink
├── sinks.py       # AuditSink ABC + InMemorySink/StructlogSink/S3JsonlSink
└── pg_sink.py     # PGSink — PostgreSQL 批量持久化（配合 migration 004）
```

---

### Sink 对比

| Sink | 环境 | 持久化 | 防篡改 | 依赖 |
|------|------|--------|--------|------|
| `StructlogSink` | 开发/降级 | ❌ (控制台) | ❌ | structlog |
| `InMemorySink` | 测试 | ❌ (内存) | ❌ | 无 |
| `PGSink` | 生产 | ✅ `audit_log` 表 | ❌ (DB 管理员可改) | asyncpg |
| `S3JsonlSink` | 生产 | ✅ S3 JSONL | ✅ (Object Lock) | boto3 |

### PGSink 批量写入

```python
class PGSink(AuditSink):
    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0):
        # batch_size: 累积多少条后批量 flush
        # flush_interval: 即使未满 batch_size 也定期 flush（秒）
    
    def emit(self, record: AuditRecord) -> None:
        # 追加到内部 buffer → 达到 batch_size 或超时后 → execute INSERT 批量写入
        # 写入失败 → 降级到 stderr (StructlogSink)
```

### 审计记录生命周期

```
audit_log(event=PRIVACY_EXPORT, user_id="alice", record_count=42)
    │
    ▼
audit_log() 函数
    ├── 构建 AuditRecord(event, user_id, timestamp, record_id=uuid4, fields={...})
    ├── 调用 get_sink().emit(record)
    │   ├── PGSink: buffer → 满 batch_size 或 flush_interval → INSERT INTO audit_log
    │   └── StructlogSink: 控制台 JSON 行
    └── fire-and-forget（不等待写入完成，不抛异常）
```

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充 Sink 对比表（4 种/环境/持久化/防篡改/依赖）、PGSink 批量写入参数、审计记录生命周期流程图
- **2026-05-18** 增量更新：新增 PGSink（PostgreSQL 批量持久化）
- **2026-05-12** 完整扫描完成，新增 AuditRecord 数据模型和 S3JsonlSink 详情
- **2026-05-12** 首次 AI 上下文初始化
