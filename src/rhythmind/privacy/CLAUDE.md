# rhythmind/privacy — 隐私服务

> `[根目录(../../CLAUDE.md) > **rhythmind** > **privacy**`

---

## 模块职责

GDPR / PIPL 数据主体权利服务，提供用户数据导出与删除功能。

---

## 入口与启动

- **业务逻辑**: `from rhythmind.privacy import PrivacyService`
- **API 路由**: `privacy_router` 在 `api/main.py` 中挂载到 `/api/v1/privacy/*`

---

## 对外接口

### PrivacyService

```python
class PrivacyService:
    def __init__(self, *, session_factory, redis_client, influx_client, qmd_client) -> None: ...
    async def export_user_data(self, user_id: str) -> UserDataExport: ...
    async def delete_user_data(self, user_id: str, *, confirm_token: str) -> DeletionReport: ...
```

### 数据结构

```python
@dataclass
class UserDataExport:
    user_id: str
    exported_at: str
    schema_version: str = "1.0"
    agent_memory: list[dict[str, Any]]
    health_facts: list[dict[str, Any]]
    redis_keys: list[str]
    influx_points: int
    qmd_collections: list[str]
    notes: list[str]

@dataclass
class DeletionReport:
    user_id: str
    deleted_at: str
    successes: list[tuple[str, str]]  # (store, detail)
    failures: list[tuple[str, str]]
    @property
    def is_clean(self) -> bool: ...
```

---

## 关键依赖与配置

- **数据库**: 通过 SQLAlchemy 删除用户数据 (AgentMemory, HealthFact)
- **Redis**: 删除 LoopGuard + rate-limit keys (`loop:{user_id}:*`, `rl:user:*:{user_id}`, `session:{user_id}:*`)
- **InfluxDB**: 删除用户时序数据点
- **QMD**: 删除用户向量索引 (`user_{user_id}_memory`, `user_{user_id}_facts`)
- **配置**: `settings.qmd_url`, `settings.redis_url`, `settings.influxdb_token`

---

## 数据模型

无独立数据模型，操作现有存储（DB/Redis/InfluxDB/QMD）。

---

## 测试与质量

- 测试目录：`tests/` 下有 privacy 相关测试
- 代码风格：`ruff check src/rhythmind/privacy/`

---

## 常见问题 (FAQ)

**Q: 删除失败会怎样？**  
A: 返回 `DeletionReport`，包含各存储的操作结果，任一失败不阻断其他删除，审计日志记录 `privacy.delete_failure`。

**Q: 导出数据包含哪些内容？**  
A: 健康事实 (health_facts)、会话记忆 (agent_memory)、用户技能、训练记录等。

**Q: confirm_token 是什么？**  
A: 必须等于 user_id，作为简单的"复述用户名"防误删机制。生产可升级为 email OTP / TOTP。

---

## 相关文件清单

```
src/rhythmind/privacy/
├── __init__.py     # 公开 API: PrivacyService, UserDataExport, DeletionReport
└── service.py     # 业务逻辑实现
```

---

## API 端点

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| `POST` | `/api/v1/privacy/export` | 导出用户全部数据 | JWT |
| `POST` | `/api/v1/privacy/delete` | 删除用户全部数据（需 confirm_token） | JWT |

### 导出请求/响应

```python
# POST /api/v1/privacy/export
Response 200:
{
    "user_id": "alice",
    "exported_at": "2026-06-11T10:00:00+00:00",
    "schema_version": "1.0",
    "agent_memory": [{"id": 1, "namespace": ..., "key": ..., "value": ...}],
    "health_facts": [{"id": 1, "subject": "profile", "predicate": "gender", ...}],
    "redis_keys": ["loop:alice:coach", "rl:user:*:alice", "session:alice:*"],
    "influx_points": 1520,
    "qmd_collections": ["user_alice_memory", "user_alice_facts"],
    "notes": []
}
```

### 删除请求/响应

```python
# POST /api/v1/privacy/delete  body: {"confirm_token": "alice"}
Response 200:
{
    "user_id": "alice",
    "deleted_at": "2026-06-11T10:00:00+00:00",
    "is_clean": true,
    "successes": [
        {"store": "agent_memory", "detail": "deleted 42 rows"},
        {"store": "health_fact", "detail": "deleted 15 rows"},
        {"store": "redis", "detail": "deleted 5 keys"},
        {"store": "influxdb", "detail": "delete predicate dispatched"},
        {"store": "qmd", "detail": "purged user_alice_memory + user_alice_facts"}
    ],
    "failures": []
}
```

## 导出/删除流程

```
POST /api/v1/privacy/export
    │
    ├─ 1. PG agent_memory ─→ SELECT WHERE user_id
    ├─ 2. PG health_fact   ─→ SELECT WHERE user_id
    ├─ 3. Redis keys       ─→ SCAN loop:{uid}:* + rl:user:*:{uid} + session:{uid}:*
    ├─ 4. InfluxDB count   ─→ query_range fields=* start=-30d → count data points
    └─ 5. QMD collections  ─→ 枚举 user_{uid}_memory + user_{uid}_facts
         │
         ▼
    UserDataExport (JSON-friendly, schema v1.0)

POST /api/v1/privacy/delete  {confirm_token: "alice"}
    │
    ├─ confirm_token != user_id → HTTP 400 (防误删)
    ├─ 1. DELETE FROM agent_memory WHERE user_id
    ├─ 2. DELETE FROM health_fact WHERE user_id
    ├─ 3. Redis: DEL <keys> (SCAN 匹配后批量删除)
    ├─ 4. InfluxDB: delete predicate (user_id tag)
    └─ 5. QMD: purge_user(user_id) → 删除 user_{uid}_memory + user_{uid}_facts
         │
         ▼
    DeletionReport (successes + failures, is_clean 检查)
```

### Redis Key 模式

| 模式 | 用途 | 示例 |
|------|------|------|
| `loop:{user_id}:*` | LoopGuard 节流计数 | `loop:alice:coach_agent` |
| `rl:user:*:{user_id}` | 用户级限流 | `rl:user:dashboard:alice` |
| `session:{user_id}:*` | 会话缓存 | `session:alice:abc123` |

### 安全设计

- **防误删**: `confirm_token` 必须等于 `user_id`（生产可升级为 email OTP/TOTP）
- **不可逆**: 删除后数据无法恢复，调用方应先调 export 备份
- **Best-effort**: 任一存储失败不阻断其余删除，返回明细报告
- **审计**: 每次 export/delete 写入 audit_log (`PRIVACY_EXPORT` / `PRIVACY_DELETE`)
- **PII 约束**: 导出数据中不包含明文 PII（name_hash 脱敏）

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充 API 端点表、导出/删除完整流程图、请求/响应示例、Redis Key 模式表、安全设计说明
- **2026-05-12** 完整扫描完成，新增数据结构和服务详情
- **2026-05-12** 首次 AI 上下文初始化
