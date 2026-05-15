# rhythmind/agents — AG2 Swarm 智能体

> `[根目录](../../CLAUDE.md) > **rhythmind** > **agents**`

---

## 模块职责

基于 AG2 (AutoGen) AgentChat 的 Swarm 流水线实现，包含三个专用 Agent：

- **MetricsAgent**: 指标采集，InfluxDB 写入 + 趋势分析 + 规则异常检测（无 LLM 调用）
- **DataAgent**: 数据分析，接收 MetricsAgent 输出后进行 LLM 深度解读
- **CoachAgent**: 健康教练，基于 DataAgent 报告生成个性化训练计划

---

## 入口与启动

- **入口**: `from rhythmind.agents import DataAgent, CoachAgent, MetricsAgent`
- **基类**: `rhythmind.core.hermes_base.HermesBase`
- **启动方式**: 由 `AgentPool.acquire()` 获取实例或直接实例化

---

## 对外接口

### MetricsAgent

```python
class MetricsAgent(HermesBase):
    def __init__(self, user_id: str, influx: InfluxClient | None = None) -> None: ...
```

输出 `AgentResult.output` = `MetricsAnalysis`:
```python
{
    "user_id": str,
    "timestamp": str,  # ISO8601 UTC
    "metrics": dict,   # 本次原始指标
    "trends": dict,    # 7日趋势摘要
    "anomalies": [{"field": str, "value": float, "expected": str, "severity": "warn"|"critical"}],
    "load_level": str,  # very_low | low | moderate | high | very_high
    "write_ok": bool,
    "influx_available": bool
}
```

### DataAgent

```python
class DataAgent(HermesBase):
    def __init__(self, user_id: str) -> None: ...
```

输入 `input_data["metrics_analysis"]` = MetricsAgent 输出  
输出 `AgentResult.output` = `DataReport`:
```python
{
    "summary": str,
    "highlights": [str],
    "concerns": [str],
    "metrics_compared": dict,
    "next_suggestion": str,
    "anomaly_digest": str
}
```

### CoachAgent

```python
class CoachAgent(HermesBase):
    def __init__(self, user_id: str) -> None: ...
```

输入 `input_data["data_report"]` = DataAgent 输出  
输出 `AgentResult.output` = `TrainingPlan`:
```python
{
    "today_plan": {...},
    "weekly_load": str,
    "recovery_advice": str,
    "motivation": str
}
```

---

## 关键依赖与配置

- **AG2**: `autogen-agentchat`, `autogen-ext[openai]`
- **Hermes 基类**: `HermesBase`（6 步执行循环）
- **模型路由**: `AdapterRouter`（由 HermesBase.call_llm 调用）
- **配置**: `rhythmind.config.settings`

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

---

## 测试与质量

- 测试目录：`tests/unit/` 下有对应测试文件
- 代码风格：`ruff check src/rhythmind/agents/`
- **195 单元 + 8 集成** = 203 个测试（来自根 CLAUDE.md）

---

## 常见问题 (FAQ)

**Q: Agent 之间如何传递上下文？**  
A: 通过 `SwarmDataCoach` 工作流编排，`input_data` 字典在链中传递。

**Q: 如何新增一个 Agent？**  
A: 继承 `HermesBase`，实现 `execute()` 抽象方法，注册到 `SwarmDataCoach`。

**Q: MetricsAgent 为何不需要 LLM？**  
A: 纯规则引擎处理数值，低延迟；异常检测和负荷分级基于阈值。

---

## 相关文件清单

```
src/rhythmind/agents/
├── __init__.py           # 公开 API: DataAgent, CoachAgent, MetricsAgent
├── data_agent.py        # 数据分析 Agent (LLM 解读)
├── coach_agent.py       # 健康教练 Agent (训练计划)
└── metrics_agent.py     # 指标采集 Agent (规则引擎)
```

---

## 变更记录 (Changelog)

- **2026-05-12** 完整扫描完成，新增 MetricsAgent 文档
- **2026-05-12** 首次 AI 上下文初始化
