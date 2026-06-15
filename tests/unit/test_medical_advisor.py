# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_medical_advisor.py — MedicalAdvisor 单元测试

覆盖场景：
  - analyze 任务正常流程
  - timeline / medications / labs 任务分别触发对应 prompt 构建器
  - 无效 task_type 降级到 analyze
  - ComplianceBlockedError 上抛
  - LLM 异常降级到 fallback
  - 置信度随活跃诊断/用药数量降低
  - requires_human_review 在高活跃诊断时触发
  - memory_updates 正确填充
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from rhythmind.agents.medical_advisor import MedicalAdvisor
from rhythmind.core.hermes_base import AgentContext, ComplianceBlockedError
from rhythmind.core.memory.types import MemoryRecallResult

USER_ID = "test_user_med"

DIAGNOSES = [
    {
        "diagnosis_name": "腰椎间盘突出",
        "diagnosis_date": "2024-06-15",
        "diagnosis_type": "chronic",
        "icd_code": "M51.1",
        "hospital": "市第一人民医院",
        "is_active": True,
    },
]

MEDICATIONS = [
    {
        "medication_name": "塞来昔布",
        "dose": "200mg",
        "route": "口服",
        "frequency": "每日一次",
        "purpose": "消炎止痛",
        "start_date": "2024-06-15",
        "end_date": None,
        "status": "active",
        "prescriber": "骨科",
    },
    {
        "medication_name": "甲钴胺",
        "dose": "0.5mg",
        "route": "口服",
        "frequency": "每日三次",
        "purpose": "营养神经",
        "start_date": "2024-06-15",
        "end_date": None,
        "status": "active",
        "prescriber": "骨科",
    },
]

LAB_RESULTS = [
    {
        "test_name": "血沉",
        "test_date": "2024-07-01",
        "value": 15.0,
        "value_str": None,
        "unit": "mm/h",
        "ref_range": "0-20",
        "flag": None,
    },
    {
        "test_name": "CRP",
        "test_date": "2024-07-01",
        "value": 3.2,
        "value_str": None,
        "unit": "mg/L",
        "ref_range": "0-8",
        "flag": None,
    },
]

EVENTS = [
    {
        "event_date": "2024-06-15T10:00:00+08:00",
        "event_type": "住院",
        "hospital": "市第一人民医院",
        "department": "骨科",
        "duration_days": 7,
        "cost": 15000.0,
    },
]

VALID_ANALYSIS = {
    "summary": "患者腰椎间盘突出术后恢复良好，炎症指标正常。",
    "insights": ["术后 CRP 和血沉均在正常范围"],
    "concerns": ["需关注长期用药的胃肠道副作用"],
    "recommendations": ["建议定期复查血沉和 CRP", "注意腰部保护"],
    "risk_flags": [],
}


def _make_ctx(task_type: str = "analyze", extra: dict | None = None) -> AgentContext:
    inp = {
        "task_type": task_type,
        "patient": {"gender": "男", "birth_year": 1970},
        "diagnoses": DIAGNOSES,
        "events": EVENTS,
        "lab_results": LAB_RESULTS,
        "medications": MEDICATIONS,
    }
    if extra:
        inp.update(extra)
    return AgentContext(
        user_id=USER_ID,
        session_id="sess-med-001",
        task_type="medical_analyze",
        input_data=inp,
    )


def _make_memory() -> MemoryRecallResult:
    return MemoryRecallResult(entries=[], total=0)


# ── 测试：analyze 正常流程 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_analyze_normal():
    """analyze 正常流程：返回完整分析结果。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_ANALYSIS))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(), memory_ctx=_make_memory())

    assert result.output["summary"] == VALID_ANALYSIS["summary"]
    assert len(result.output["insights"]) > 0
    assert result.confidence > 0.50
    assert result.requires_human_review is False


# ── 测试：timeline 任务 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_timeline_task():
    """timeline 任务应调用 _build_timeline_prompt。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    timeline_result = {
        "summary": "2024年有一次住院记录。",
        "insights": ["骨科住院7天"],
        "concerns": [],
        "recommendations": ["定期复查"],
        "risk_flags": [],
    }
    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(timeline_result))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(task_type="timeline"), memory_ctx=_make_memory())  # noqa: E501

    assert result.output["summary"] != ""


# ── 测试：medications 任务 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_medications_task():
    """medications 任务应返回用药审查。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    med_result = {
        "summary": "当前2种在用药物。",
        "insights": ["塞来昔布与甲钴胺无已知严重交互"],
        "concerns": ["长期使用NSAIDs需监测肾功能"],
        "recommendations": ["定期检查肾功能"],
        "risk_flags": [],
    }
    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(med_result))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(task_type="medications"), memory_ctx=_make_memory())  # noqa: E501

    assert result.output["summary"] != ""


# ── 测试：labs 任务 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_labs_task():
    """labs 任务应返回化验趋势解读。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    lab_result = {
        "summary": "血沉和CRP均在正常范围。",
        "insights": ["炎症指标稳定"],
        "concerns": [],
        "recommendations": ["继续定期监测"],
        "risk_flags": [],
    }
    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(lab_result))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(task_type="labs"), memory_ctx=_make_memory())  # noqa: E501

    assert result.output["summary"] != ""


# ── 测试：无效 task_type 降级 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_invalid_task_defaults_to_analyze():
    """无效 task_type 应降级到 analyze。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_ANALYSIS))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(task_type="unknown_type"), memory_ctx=_make_memory())  # noqa: E501

    assert result.output["summary"] != ""


# ── 测试：ComplianceBlockedError 上抛 ───────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_compliance_blocked_propagates():
    """call_llm 抛 ComplianceBlockedError 时应上抛。"""
    agent = MedicalAdvisor(user_id=USER_ID)
    err = ComplianceBlockedError("prompt 审查拦截", audit=None)

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=err)):
        with pytest.raises(ComplianceBlockedError):
            await agent.execute(ctx=_make_ctx(), memory_ctx=_make_memory())


# ── 测试：LLM 异常降级 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_llm_exception_uses_fallback():
    """call_llm 抛通用异常时使用 fallback。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=ConnectionError("model down"))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(), memory_ctx=_make_memory())

    assert "不可用" in result.output["summary"]
    assert result.output["recommendations"] != []


@pytest.mark.asyncio
async def test_medical_advisor_invalid_json_uses_fallback():
    """call_llm 返回无法解析的 JSON 时使用 fallback。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value="not json")):
        result = await agent.execute(ctx=_make_ctx(), memory_ctx=_make_memory())

    assert result.output is not None
    assert "summary" in result.output


# ── 测试：置信度随活跃诊断降低 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_confidence_decreases_with_diagnoses():
    """多个活跃诊断时置信度应降低。"""
    agent = MedicalAdvisor(user_id=USER_ID)
    many_diagnoses = [
        {"diagnosis_name": f"诊断{i}", "diagnosis_date": "2024-01-01",
         "diagnosis_type": "chronic", "is_active": True}
        for i in range(5)
    ]

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_ANALYSIS))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(extra={"diagnoses": many_diagnoses}),
            memory_ctx=_make_memory(),
        )

    assert result.confidence < 0.88


# ── 测试：requires_human_review 触发 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_human_review_with_many_diagnoses():
    """活跃诊断 >= 3 时 requires_human_review=True。"""
    agent = MedicalAdvisor(user_id=USER_ID)
    three_diagnoses = [
        {"diagnosis_name": f"诊断{i}", "diagnosis_date": "2024-01-01",
         "diagnosis_type": "chronic", "is_active": True}
        for i in range(3)
    ]

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_ANALYSIS))):  # noqa: E501
        result = await agent.execute(
            ctx=_make_ctx(extra={"diagnoses": three_diagnoses}),
            memory_ctx=_make_memory(),
        )

    assert result.requires_human_review is True


# ── 测试：memory_updates ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_medical_advisor_memory_updates_populated():
    """memory_updates 应包含分析和统计信息。"""
    agent = MedicalAdvisor(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_ANALYSIS))):  # noqa: E501
        result = await agent.execute(ctx=_make_ctx(), memory_ctx=_make_memory())

    assert "last_medical_summary" in result.memory_updates
    assert "medical_task_type" in result.memory_updates
    assert "active_diagnoses_count" in result.memory_updates
    assert "active_medications_count" in result.memory_updates


# ── 测试：prompt 构建器 ──────────────────────────────────────────────────────

def test_build_analyze_prompt_contains_diagnoses():
    """analyze prompt 应包含诊断名称。"""
    prompt = MedicalAdvisor._build_analyze_prompt(
        patient={"gender": "男", "birth_year": 1970},
        diagnoses=DIAGNOSES,
        events=EVENTS,
        lab_results=LAB_RESULTS,
        medications=MEDICATIONS,
        prior_summary={},
    )
    assert "腰椎间盘突出" in prompt
    assert "塞来昔布" in prompt
    assert "不得" in prompt


def test_build_labs_prompt_groups_by_test():
    """labs prompt 应按检查名分组。"""
    prompt = MedicalAdvisor._build_labs_prompt(
        patient={},
        diagnoses=[],
        events=[],
        lab_results=LAB_RESULTS,
        medications=[],
        prior_summary={},
    )
    assert "血沉" in prompt
    assert "CRP" in prompt


def test_build_medications_prompt_separates_active():
    """medications prompt 应区分活跃和历史用药。"""
    all_meds = MEDICATIONS + [
        {**MEDICATIONS[0], "status": "discontinued", "end_date": "2024-08-01"},
    ]
    prompt = MedicalAdvisor._build_medications_prompt(
        patient={},
        diagnoses=DIAGNOSES,
        events=[],
        lab_results=[],
        medications=all_meds,
        prior_summary={},
    )
    assert "当前用药" in prompt
    assert "历史用药" in prompt


# ── 测试：fallback_result ─────────────────────────────────────────────────────

def test_fallback_result_structure():
    """fallback 应包含完整的 5 个字段。"""
    result = MedicalAdvisor._fallback_result("analyze", DIAGNOSES, MEDICATIONS)
    assert "summary" in result
    assert "insights" in result
    assert "concerns" in result
    assert "recommendations" in result
    assert "risk_flags" in result
