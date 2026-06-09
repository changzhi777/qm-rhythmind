# rhythmind/orchestrator — 流水线编排层

> `[根目录(../../CLAUDE.md) > **rhythmind** > **orchestrator**`

---

## 模块职责

任务路由与 Swarm 工作流编排：

- **HealthRouter**: 意图分类 → 路由到对应工作流 → 前置合规检查 → LoopGuard 节流
- **SwarmDataCoach**: 三阶段 Swarm 流水线（MetricsAgent → DataAgent → CoachAgent）
- **LoopGuard**: 防无限循环节流（24h TTL，分级限流：greeting 10次、query 30次、__default__ 5次）
- **AgentPool**: LRU Agent 实例缓存（max_users=2000, ttl=3600s）

---

## 入口与启动

- **入口**: `from rhythmind.orchestrator import HealthRouter`
- **实例化**: `HealthRouter()` 通过 `api/deps.py` 的 `get_pool()` 获取单例
- **启动方式**: 由 FastAPI 路由在收到请求时调用

---

## 对外接口

### HealthRouter

```python
class HealthRouter:
    def __init__(self) -> None: ...
    async def route(self, user_id: str, raw_input: dict, session_id: str | None = None) -> WorkflowResult: ...
    async def close(self) -> None: ...
```

### SwarmDataCoach

```python
class SwarmDataCoach:
    async def run(self, user_id, session_id, input_data, metrics_agent, data_agent, coach_agent) -> SwarmResult: ...
    async def run_stream(self, ...) -> AsyncGenerator[dict[str, str], None]: ...  # SSE 流式
```

### LoopGuard

```python
class LoopGuard:
    async def is_cooling_down(self, user_id: str, intent: str) -> bool: ...
    async def reset(self, user_id: str, intent: str) -> None: ...
    async def close(self) -> None: ...
    # True = 允许执行，False = 被节流拦截
```

### AgentPool

```python
class AgentPool:
    def __init__(self, max_users: int = 500, ttl_seconds: float = 1800) -> None: ...
    @asynccontextmanager
    async def acquire(self, user_id: str) -> AsyncGenerator[AgentBundle, None]: ...
    async def invalidate(self, user_id: str) -> None: ...
    async def purge_expired(self) -> int: ...
    def stats(self) -> dict: ...
```

### WorkflowStatus

```python
class WorkflowStatus(StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"      # ComplianceGate 拦截
    THROTTLED = "throttled"  # LoopGuard 节流
    ERROR = "error"          # 未预期异常
```

### WorkflowResult

```python
@dataclass
class WorkflowResult:
    status: WorkflowStatus
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    session_id: str = ""
    user_id: str = ""
```

### SwarmResult

```python
@dataclass
class SwarmResult:
    metrics_result: HermesRunResult
    data_result: HermesRunResult
    coach_result: HermesRunResult
    success: bool
    user_id: str
    session_id: str

    @property
    def final_output(self) -> dict[str, Any]: ...
```

### AgentBundle

```python
@dataclass
class AgentBundle:
    user_id: str
    metrics: MetricsAgent
    data: DataAgent
    coach: CoachAgent
    created_at: float
    last_used: float
```

---

## 关键依赖与配置

- **Agent**: `MetricsAgent`, `DataAgent`, `CoachAgent`
- **合规**: `ComplianceGate`
- **Redis**: LoopGuard 依赖 `redis.asyncio`
- **配置**: `settings.loop_guard_ttl_hours`, `settings.loop_guard_max_calls`, `settings.agent_pool_max_users`, `settings.agent_pool_ttl`

---

## 数据模型

无持久化数据模型。

---

## 测试与质量

- 测试目录：`tests/unit/` 下有 orchestrator 相关测试
- 代码风格：`ruff check src/rhythmind/orchestrator/`

---

## 常见问题 (FAQ)

**Q: LoopGuard 如何防止无限循环？**  
A: 同一 user_id + intent 在 24h 内最多触发 3 次，超过后返回 `THROTTLED` 状态。

**Q: AgentPool 的 LRU 策略如何工作？**  
A: 使用 `OrderedDict` 维护顺序，最近使用的移到末尾；池满时淘汰头部（最久未使用）。

**Q: Swarm 工作流的 handoff 机制是什么？**  
A: AG2 AgentChat 的内置机制，Agent 之间通过 `handoff` 传递控制权（Phase 2 计划）。

**Q: run_ag2_swarm() 是什么？**  
A: Phase 2 计划中的真实 AutoGen Swarm 集成，当前为手动链 `SwarmDataCoach.run()`。

---

## 相关文件清单

```
src/rhythmind/orchestrator/
├── __init__.py              # 公开 API: HealthRouter, WorkflowResult, WorkflowStatus
├── router.py               # HealthRouter 主逻辑 + 意图分类
├── loop_guard.py           # LoopGuard 节流实现 (Redis TTL)
├── pool.py                 # AgentPool LRU 实例缓存
└── workflows/
    ├── __init__.py
    └── swarm_data_coach.py # SwarmDataCoach 三阶段流水线
```

---

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增 AgentPool、SwarmResult、AgentBundle 详情
- **2026-05-12** 首次 AI 上下文初始化
