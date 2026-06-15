# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_data_agent.py — DataAgent 单元测试

覆盖场景：
  - 正常流程：call_llm 返回合法 JSON → AgentResult 置信度正确
  - 上游 metrics_analysis 缺失 → 降级使用 raw input_data
  - call_llm 抛 ComplianceBlockedError → 上抛
  - call_llm 抛通用异常 → fallback_report 降级
  - anomalies 数量影响置信度计算
  - requires_human_review 在 critical 异常时触发
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from rhythmind.agents.data_agent import DataAgent
from rhythmind.core.hermes_base import AgentContext, ComplianceBlockedError
from rhythmind.core.memory.types import MemoryEntry, MemoryRecallResult, MemoryType

# ── Fixtures ──────────────────────────────────────────────────────────────────

USER_ID = "test_user_data"

METRICS_ANALYSIS = {
    "user_id": USER_ID,
    "timestamp": "2025-05-09T10:00:00+00:00",
    "metrics": {
        "heart_rate_avg": 145.0,
        "heart_rate_max": 178.0,
        "steps": 8500,
        "distance_km": 6.2,
        "calories": 480,
        "sleep_hours": 7.5,
        "hrv": 55.0,
        "body_fat_pct": None,
        "muscle_mass_kg": None,
        "water_pct": None,
        "visceral_fat": None,
    },
    "trends": {
        "heart_rate_avg": {
            "avg": 140.0, "latest": 145.0, "oldest": 135.0, "delta": 10.0, "points": 7
        },
    },
    "anomalies": [],
    "load_level": "moderate",
    "write_ok": True,
    "influx_available": True,
}

VALID_REPORT = {
    "summary": "本次训练状态良好，心率控制在合理范围。",
    "highlights": ["心率稳定", "睡眠充足", "步数达标"],
    "concerns": [],
    "metrics_compared": {
        "heart_rate_avg": {"current": 145.0, "trend_avg": 140.0, "trend": "↑"},
    },
    "next_suggestion": "明天可以尝试适当提升训练强度。",
    "anomaly_digest": "各项指标正常",
}


def _make_ctx(extra_input: dict | None = None) -> AgentContext:
    inp = {"metrics_analysis": METRICS_ANALYSIS, "sport_type": "running"}
    if extra_input:
        inp.update(extra_input)
    return AgentContext(
        user_id=USER_ID,
        session_id="sess-data-001",
        task_type="upload_data",
        input_data=inp,
    )


def _make_memory(extra_keys: dict | None = None) -> MemoryRecallResult:
    entries = []
    if extra_keys:
        for k, v in extra_keys.items():
            entries.append(MemoryEntry(
                namespace=f"user.{USER_ID}.data_agent.{k}",
                key=k, value=v,
                mem_type=MemoryType.PROJECT,
            ))
    return MemoryRecallResult(entries=entries, total=len(entries))



# ── 测试：正常流程 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_normal_flow():
    """正常流程：call_llm 返回合法 JSON，AgentResult 应有正确置信度。"""
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory({}),
        )

    assert result.output["summary"] == VALID_REPORT["summary"]
    assert result.output["anomaly_digest"] == "各项指标正常"
    # 无 anomalies → base confidence = 0.92
    assert result.confidence == pytest.approx(0.92, abs=0.01)
    assert result.requires_human_review is False


@pytest.mark.asyncio
async def test_data_agent_confidence_decreases_with_anomalies():
    """有 critical 异常时置信度应降低，requires_human_review=True。"""
    analysis_with_anomaly = {
        **METRICS_ANALYSIS,
        "anomalies": [
            {
                "field": "heart_rate_max",
                "value": 210.0,
                "expected": "[50, 200]",
                "severity": "critical",
            }
        ],
        "metrics": {**METRICS_ANALYSIS["metrics"], "heart_rate_max": 210.0},
    }
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx({"metrics_analysis": analysis_with_anomaly}),
            memory_ctx=_make_memory({}),
        )

    # 1 critical: 0.92 - 0.20 = 0.72
    assert result.confidence == pytest.approx(0.72, abs=0.01)
    assert result.requires_human_review is True


@pytest.mark.asyncio
async def test_data_agent_warn_anomaly_reduces_confidence():
    """warn 级异常置信度降低幅度较小。"""
    analysis_with_warn = {
        **METRICS_ANALYSIS,
        "anomalies": [
            {
                "field": "sleep_hours",
                "value": 3.5,
                "expected": "[4, 12]",
                "severity": "warn",
            }
        ],
    }
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx({"metrics_analysis": analysis_with_warn}),
            memory_ctx=_make_memory({}),
        )

    # 1 warn: 0.92 - 0.08 = 0.84
    assert result.confidence == pytest.approx(0.84, abs=0.01)
    assert result.requires_human_review is False


# ── 测试：缺失上游分析 ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_no_metrics_analysis_fallback():
    """缺失 metrics_analysis 时，应降级使用 raw input_data 中的字段。"""
    agent = DataAgent(user_id=USER_ID)
    raw_ctx = AgentContext(
        user_id=USER_ID,
        session_id="sess-data-002",
        task_type="upload_data",
        input_data={
            "heart_rate_avg": 130.0,
            "steps": 5000,
            "sleep_hours": 6.0,
        },
    )

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=raw_ctx,
            memory_ctx=_make_memory({}),
        )

    # 降级后仍能返回结果
    assert result.output is not None
    assert "summary" in result.output


# ── 测试：ComplianceBlockedError 上抛 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_compliance_blocked_propagates():
    """call_llm 抛 ComplianceBlockedError 时，execute 应将其上抛。"""
    agent = DataAgent(user_id=USER_ID)

    blocked_error = ComplianceBlockedError("测试拦截", audit=None)
    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=blocked_error)):
        with pytest.raises(ComplianceBlockedError):
            await agent.execute(
                ctx=_make_ctx(),
                memory_ctx=_make_memory({}),
            )


# ── 测试：LLM 异常降级 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_llm_exception_uses_fallback():
    """call_llm 抛通用异常时，应返回 fallback_report 而非崩溃。"""
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=RuntimeError("LLM timeout"))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory({}),
        )

    assert "数据解读服务暂时不可用" in result.output["summary"]
    assert result.output["next_suggestion"] != ""


@pytest.mark.asyncio
async def test_data_agent_invalid_json_uses_fallback():
    """call_llm 返回无法解析的 JSON 时，使用 fallback。"""
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value="not valid json {{{")):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory({}),
        )

    assert result.output is not None


# ── 测试：memory_updates ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_memory_updates_populated():
    """memory_updates 应包含 metrics_baseline 和 last_report_date。"""
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory({}),
        )

    assert "metrics_baseline" in result.memory_updates
    assert "last_report_date" in result.memory_updates
    assert "sport_type_preference" in result.memory_updates


# ── 测试：skill_candidates ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_data_agent_skill_candidates_include_sport_type():
    """skill_candidates 应含运动类型标识。"""
    agent = DataAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_REPORT))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx({"sport_type": "cycling"}),
            memory_ctx=_make_memory({}),
        )

    assert any("cycling" in c for c in result.skill_candidates)


# ── 测试：prompt 构建 ────────────────────────────────────────────────────────

def test_build_prompt_no_trends():
    """无趋势数据时 prompt 应包含 InfluxDB 不可用提示。"""
    prompt = DataAgent._build_prompt(
        metrics={"heart_rate_avg": 140.0},
        trends={},
        anomalies=[],
        load_level="moderate",
        baseline={},
        sport_type="running",

    )
    assert "InfluxDB 不可用" in prompt


def test_build_prompt_with_anomalies():
    """有异常时 prompt 应包含异常字段名。"""
    prompt = DataAgent._build_prompt(
        metrics={"heart_rate_max": 210.0},
        trends={},
        anomalies=[
            {
                "field": "heart_rate_max",
                "value": 210.0,
                "expected": "[50, 200]",
                "severity": "critical",
            }
        ],
        load_level="high",
        baseline={},
        sport_type="running",

    )
    assert "heart_rate_max" in prompt
    assert "⛔" in prompt


def test_fallback_report_with_anomalies():
    """fallback_report 应将 anomalies 转化为 concerns 列表。"""
    anomalies = [
        {"field": "hrv", "value": 4.0, "expected": "[10, 200]", "severity": "critical"}
    ]
    report = DataAgent._fallback_report(metrics={}, anomalies=anomalies)
    assert len(report["concerns"]) == 1
    assert "hrv" in report["concerns"][0]
    assert "数据解读服务暂时不可用" in report["summary"]
