# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_swarm_data_coach.py — SwarmDataCoach 单元测试

覆盖场景：
  - 正常三级链：MetricsAgent → DataAgent → CoachAgent 全部成功
  - DataAgent BLOCK → 提前返回，coach 为空失败结果
  - CoachAgent BLOCK → success=False，前两级结果仍保留
  - final_output 结构完整性验证
  - run_stream() SSE 事件序列正确
  - 池化 Agent 注入（metrics/data/coach 参数）正常工作
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult
from rhythmind.core.hermes_base import AgentContext, HermesRunResult
from rhythmind.orchestrator.workflows.swarm_data_coach import (
    SwarmDataCoach,
    SwarmResult,
)

# ── 工厂：构造 HermesRunResult ────────────────────────────────────────────────

def _make_run_result(
    output: dict,
    success: bool = True,
    agent: str = "test_agent",
    latency_ms: float = 50.0,
) -> HermesRunResult:
    level = ComplianceLevel.PASS if success else ComplianceLevel.BLOCK
    compliance = ComplianceResult(
        level=level,
        output=output if success else None,
        confidence=0.90 if success else 0.0,
        compliance_block=not success,
    )
    return HermesRunResult(
        compliance=compliance,
        agent=agent,
        user_id="test_user",
        task_type="test",
        latency_ms=latency_ms,
    )


METRICS_OUTPUT = {
    "user_id": "test_user",
    "timestamp": "2025-05-09T10:00:00+00:00",
    "metrics": {"heart_rate_avg": 145.0, "steps": 8000, "distance_km": 5.0},
    "trends": {},
    "anomalies": [],
    "load_level": "moderate",
    "write_ok": True,
    "influx_available": True,
}

DATA_OUTPUT = {
    "summary": "训练状态良好",
    "highlights": ["心率稳定"],
    "concerns": [],
    "metrics_compared": {},
    "next_suggestion": "明天可提升强度",
    "anomaly_digest": "各项指标正常",
}

COACH_OUTPUT = {
    "today_plan": {
        "name": "轻松慢跑",
        "duration_min": 40,
        "distance_km": 5.0,
        "intensity": "低",
        "hr_target_zone": "Z2",
        "exercises": ["慢跑 30 分钟"],
        "warm_up": "热身 5 分钟",
        "cool_down": "拉伸 5 分钟",
    },
    "weekly_load": "建议累计 30 km",
    "recovery_advice": "充足睡眠",
    "motivation": "坚持就是胜利！",
}


USER_ID = "test_user"
SESSION_ID = "sess-swarm-001"
INPUT_DATA = {"source": "garmin", "sport_type": "running", "heart_rate_avg": 145.0, "steps": 8000}


# ── 测试：正常三级链 ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_run_all_success():
    """三个 Agent 全部成功时，SwarmResult.success=True，final_output 字段完整。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent")

    swarm = SwarmDataCoach()
    result = await swarm.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    )

    assert result.success is True
    fo = result.final_output
    assert fo["metrics_analysis"] == METRICS_OUTPUT
    assert fo["data_report"] == DATA_OUTPUT
    assert fo["training_plan"] == COACH_OUTPUT
    assert fo["anomaly_count"] == 0
    assert fo["load_level"] == "moderate"
    assert "total" in fo["latency_ms"]


@pytest.mark.asyncio
async def test_swarm_run_handoff_data_receives_metrics_analysis():
    """DataAgent 的 run() 调用应携带 metrics_analysis（handoff 验证）。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent")

    swarm = SwarmDataCoach()
    await swarm.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    )

    # DataAgent 收到的 ctx 应含 metrics_analysis
    data_ctx: AgentContext = data_mock.run.call_args[0][0]
    assert "metrics_analysis" in data_ctx.input_data
    assert data_ctx.input_data["metrics_analysis"] == METRICS_OUTPUT


@pytest.mark.asyncio
async def test_swarm_run_handoff_coach_receives_data_report():
    """CoachAgent 的 run() 调用应携带 data_report 和 metrics_analysis（透传）。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent")

    swarm = SwarmDataCoach()
    await swarm.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    )

    coach_ctx: AgentContext = coach_mock.run.call_args[0][0]
    assert "data_report" in coach_ctx.input_data
    assert "metrics_analysis" in coach_ctx.input_data
    assert coach_ctx.input_data["data_report"] == DATA_OUTPUT


# ── 测试：DataAgent BLOCK ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_run_data_agent_blocked_stops_chain():
    """DataAgent BLOCK 时，CoachAgent 不应被调用，success=False。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result({}, success=False, agent="data_agent")

    coach_mock = AsyncMock()

    swarm = SwarmDataCoach()
    result = await swarm.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    )

    assert result.success is False
    coach_mock.run.assert_not_called()
    # coach_result 应是空的失败结果（非 None）
    assert result.coach_result is not None
    assert result.coach_result.compliance.level == ComplianceLevel.BLOCK


# ── 测试：CoachAgent BLOCK ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_run_coach_agent_blocked_overall_fails():
    """CoachAgent BLOCK 时，success=False，但前两级结果仍保留。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result({}, success=False, agent="coach_agent")

    swarm = SwarmDataCoach()
    result = await swarm.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    )

    assert result.success is False
    assert result.metrics_result.output == METRICS_OUTPUT
    assert result.data_result.output == DATA_OUTPUT


# ── 测试：run_stream() SSE 事件序列 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_swarm_run_stream_event_sequence():
    """run_stream() 应按顺序产出 start/metrics_done/data_done/coach_done/done 事件。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent", latency_ms=30.0)

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent", latency_ms=200.0)

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent", latency_ms=180.0)

    swarm = SwarmDataCoach()
    events = []
    async for event in swarm.run_stream(
        user_id=USER_ID,
        session_id=SESSION_ID,
        input_data=INPUT_DATA,
        metrics_agent=metrics_mock,
        data_agent=data_mock,
        coach_agent=coach_mock,
    ):
        events.append(event)

    event_names = [e["event"] for e in events]
    assert event_names == ["start", "metrics_done", "data_done", "coach_done", "done"]


@pytest.mark.asyncio
async def test_swarm_run_stream_metrics_done_payload():
    """metrics_done 事件的 data 应含 load_level 和 anomaly_count。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(
        {**METRICS_OUTPUT, "anomalies": [{"field": "hrv", "severity": "warn"}], "load_level": "high"},
        agent="metrics_agent",
    )
    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent")

    swarm = SwarmDataCoach()
    events = []
    async for e in swarm.run_stream(
        user_id=USER_ID, session_id=SESSION_ID, input_data=INPUT_DATA,
        metrics_agent=metrics_mock, data_agent=data_mock, coach_agent=coach_mock,
    ):
        events.append(e)

    metrics_event = next(e for e in events if e["event"] == "metrics_done")
    payload = json.loads(metrics_event["data"])
    assert payload["load_level"] == "high"
    assert payload["anomaly_count"] == 1


@pytest.mark.asyncio
async def test_swarm_run_stream_data_blocked_yields_error():
    """DataAgent BLOCK 时，run_stream 应产出 error 事件并停止。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result({}, success=False, agent="data_agent")

    swarm = SwarmDataCoach()
    events = []
    async for e in swarm.run_stream(
        user_id=USER_ID, session_id=SESSION_ID, input_data=INPUT_DATA,
        metrics_agent=metrics_mock, data_agent=data_mock, coach_agent=None,
    ):
        events.append(e)

    event_names = [e["event"] for e in events]
    assert "error" in event_names
    assert "done" not in event_names


@pytest.mark.asyncio
async def test_swarm_run_stream_done_payload_is_complete():
    """done 事件的 data 应是完整的 final_output（含 training_plan）。"""
    metrics_mock = AsyncMock()
    metrics_mock.run.return_value = _make_run_result(METRICS_OUTPUT, agent="metrics_agent")

    data_mock = AsyncMock()
    data_mock.run.return_value = _make_run_result(DATA_OUTPUT, agent="data_agent")

    coach_mock = AsyncMock()
    coach_mock.run.return_value = _make_run_result(COACH_OUTPUT, agent="coach_agent")

    swarm = SwarmDataCoach()
    events = []
    async for e in swarm.run_stream(
        user_id=USER_ID, session_id=SESSION_ID, input_data=INPUT_DATA,
        metrics_agent=metrics_mock, data_agent=data_mock, coach_agent=coach_mock,
    ):
        events.append(e)

    done_event = next(e for e in events if e["event"] == "done")
    payload = json.loads(done_event["data"])
    assert "training_plan" in payload
    assert "data_report" in payload
    assert "metrics_analysis" in payload
    assert "confidence" in payload
    assert "latency_ms" in payload


# ── 测试：final_output 结构 ───────────────────────────────────────────────────

def test_swarm_result_final_output_structure():
    """SwarmResult.final_output 应包含所有关键字段。"""
    swarm_result = SwarmResult(
        metrics_result=_make_run_result(METRICS_OUTPUT, agent="metrics_agent"),
        data_result=_make_run_result(DATA_OUTPUT, agent="data_agent"),
        coach_result=_make_run_result(COACH_OUTPUT, agent="coach_agent"),
        success=True,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    fo = swarm_result.final_output

    required_keys = [
        "metrics_analysis", "data_report", "training_plan",
        "confidence", "anomaly_count", "load_level",
        "influx_available", "latency_ms",
    ]
    for key in required_keys:
        assert key in fo, f"final_output 缺少字段: {key}"

    assert isinstance(fo["confidence"], dict)
    assert "metrics" in fo["confidence"]
    assert "data" in fo["confidence"]
    assert "coach" in fo["confidence"]
    assert "total" in fo["latency_ms"]
