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

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增数据结构和服务详情
- **2026-05-12** 首次 AI 上下文初始化
