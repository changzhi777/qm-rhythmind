# rhythmind/agents — AG2 Swarm 智能体

> `[根目录](../../CLAUDE.md) > **rhythmind** > **agents**`

---

## 模块职责

基于 AG2 (AutoGen) AgentChat 的 Swarm 流水线实现，包含四个专用 Agent：

- **MetricsAgent**: 指标采集，InfluxDB 写入 + 趋势分析 + 规则异常检测（无 LLM 调用）
- **DataAgent**: 数据分析，接收 MetricsAgent 输出后进行 LLM 深度解读
- **CoachAgent**: 健康教练，基于 DataAgent 报告生成个性化训练计划
- **MedicalAdvisor**: 医疗顾问，基于 5 张医疗结构化表进行综合分析/时间线/用药审查/化验趋势（独立于运动健康三阶段链）

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

### MedicalAdvisor

```python
class MedicalAdvisor(HermesBase):
    def __init__(self, user_id: str) -> None: ...
```

独立于运动健康三阶段链（Metrics→Data→Coach），专注于已录入的医疗数据库数据解读。

支持四种任务类型：
- **analyze**: 综合健康分析（诊断+用药+化验趋势）
- **timeline**: 临床事件时间线梳理
- **medications**: 用药审查（交互作用+依从性）
- **labs**: 化验结果趋势解读

输入 `input_data`:
```python
{
    "task_type": "analyze" | "timeline" | "medications" | "labs",
    "patient": dict,           # MedPatientProfile 序列化（可选）
    "diagnoses": list[dict],   # MedDiagnosis 序列化列表
    "events": list[dict],      # MedClinicalEvent 序列化列表（可选）
    "lab_results": list[dict], # MedLabResult 序列化列表（可选）
    "medications": list[dict], # MedMedication 序列化列表（可选）
}
```

输出 `AgentResult.output`:
```python
{
    "summary": str,
    "insights": [str],
    "concerns": [str],
    "recommendations": [str],
    "risk_flags": [str],
}
```

合规约束：
- 系统提示明确禁止诊断性语言和处方建议
- 输出通过 ComplianceGate 后置关键词扫描
- 前置 `call_llm()` gemma 审查拦截危险意图

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
- **医疗模块测试**: `test_medical_advisor.py`（Agent 逻辑）, `test_medical_api.py`（API 路由）, `test_medical_models.py`（ORM 模型）
- **~223 单元 + 8 集成** = ~231 个测试

---

## 常见问题 (FAQ)

**Q: Agent 之间如何传递上下文？**
A: 通过 `SwarmDataCoach` 工作流编排，`input_data` 字典在链中传递。

**Q: 如何新增一个 Agent？**
A: 继承 `HermesBase`，实现 `execute()` 抽象方法，注册到 `SwarmDataCoach`。

**Q: MetricsAgent 为何不需要 LLM？**
A: 纯规则引擎处理数值，低延迟；异常检测和负荷分级基于阈值。

**Q: MedicalAdvisor 与三阶段链的关系？**
A: 完全独立。MedicalAdvisor 直读 `med_*` 表数据，不参与 Swarm 流水线。

---

## 相关文件清单

```
src/rhythmind/agents/
├── __init__.py           # 公开 API: DataAgent, CoachAgent, MetricsAgent
├── data_agent.py         # 数据分析 Agent (LLM 解读)
├── coach_agent.py        # 健康教练 Agent (训练计划)
├── metrics_agent.py      # 指标采集 Agent (规则引擎)
└── medical_advisor.py    # 医疗顾问 Agent (4 任务类型)
```

---

## 变更记录 (Changelog)

- **2026-05-21** 新增 MedicalAdvisor Agent（综合分析/时间线/用药审查/化验趋势）
- **2026-05-12** 完整扫描完成，新增 MetricsAgent 文档
- **2026-05-12** 首次 AI 上下文初始化
