# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_coach_agent.py — CoachAgent 单元测试

覆盖场景：
  - 正常流程：call_llm 返回合法训练计划 JSON
  - 训练量突增安全检查：新建议距离 > 历史 15% → confidence 降级
  - ComplianceBlockedError 上抛
  - LLM 异常 → fallback_plan 降级
  - memory_updates 正确合并历史训练量
  - 不同 user_goal 映射到正确 goal_focus
  - prompt 构建包含关键字段
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from rhythmind.agents.coach_agent import GOAL_FOCUS_MAP, CoachAgent
from rhythmind.core.hermes_base import AgentContext, ComplianceBlockedError
from rhythmind.core.memory.types import MemoryEntry, MemoryRecallResult, MemoryType

# ── Fixtures ──────────────────────────────────────────────────────────────────

USER_ID = "test_user_coach"

DATA_REPORT = {
    "summary": "本次训练状态良好，恢复充分。",
    "highlights": ["心率稳定", "睡眠质量高"],
    "concerns": [],
    "metrics_compared": {},
    "next_suggestion": "可以适当增加强度。",
    "anomaly_digest": "各项指标正常",
}

VALID_PLAN = {
    "today_plan": {
        "name": "轻松慢跑",
        "duration_min": 40,
        "distance_km": 5.0,
        "intensity": "低",
        "hr_target_zone": "Z2",
        "exercises": ["慢跑 30 分钟", "全身拉伸 10 分钟"],
        "warm_up": "动态拉伸 5 分钟",
        "cool_down": "静态拉伸 5 分钟",
    },
    "weekly_load": "本周建议累计跑量 30-35 km。",
    "recovery_advice": "保证 7-8 小时睡眠，补充优质蛋白质。",
    "motivation": "每一步都是进步，坚持就是胜利！",
}


def _make_ctx(
    user_goal: str = "健康维护",
    sport_type: str = "running",
    extra: dict | None = None,
) -> AgentContext:
    inp = {
        "data_report": DATA_REPORT,
        "sport_type": sport_type,
        "user_goal": user_goal,
    }
    if extra:
        inp.update(extra)
    return AgentContext(
        user_id=USER_ID,
        session_id="sess-coach-001",
        task_type="generate_plan",
        input_data=inp,
    )


def _make_memory(weekly_volume_km: float = 0.0, current_plan: dict | None = None) -> MemoryRecallResult:
    entries = []
    if weekly_volume_km:
        entries.append(MemoryEntry(
            namespace=f"user.{USER_ID}.coach_agent.training_history",
            key="training_history",
            value={"weekly_volume_km": weekly_volume_km},
            mem_type=MemoryType.PROJECT,
        ))
    if current_plan:
        entries.append(MemoryEntry(
            namespace=f"user.{USER_ID}.coach_agent.current_plan",
            key="current_plan",
            value=current_plan,
            mem_type=MemoryType.PROJECT,
        ))
    return MemoryRecallResult(entries=entries, total=len(entries))


# ── 测试：正常流程 ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coach_agent_normal_flow():
    """正常流程：call_llm 返回合法计划 JSON，置信度应为 0.90。"""
    agent = CoachAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_PLAN))):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(),
        )

    assert result.output["today_plan"]["name"] == "轻松慢跑"
    assert result.output["motivation"] != ""
    assert result.confidence == pytest.approx(0.90, abs=0.01)
    assert result.requires_human_review is False


@pytest.mark.asyncio
async def test_coach_agent_memory_updates_accumulate_volume():
    """memory_updates 应将新距离累加到历史周跑量中。"""
    agent = CoachAgent(user_id=USER_ID)
    existing_volume = 20.0  # 历史已有 20 km

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_PLAN))):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(weekly_volume_km=existing_volume),
        )

    new_volume = result.memory_updates["training_history"]["weekly_volume_km"]
    # VALID_PLAN distance_km=5.0, 历史 20.0 → 25.0
    assert new_volume == pytest.approx(25.0, abs=0.1)


# ── 测试：训练量突增安全检查 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coach_agent_load_spike_reduces_confidence():
    """新建议距离 > 历史周量 15% 时，confidence 应降至 0.65。"""
    agent = CoachAgent(user_id=USER_ID)
    # 历史周量 20 km，新计划 5 km > 20 * 0.15 = 3 km → 触发安全检查
    existing_volume = 20.0

    spike_plan = {
        **VALID_PLAN,
        "today_plan": {**VALID_PLAN["today_plan"], "distance_km": 8.0},
    }

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(spike_plan))):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(weekly_volume_km=existing_volume),
        )

    assert result.confidence == pytest.approx(0.65, abs=0.01)


@pytest.mark.asyncio
async def test_coach_agent_no_spike_when_no_history():
    """历史跑量为 0 时，不触发突增检查，置信度保持 0.90。"""
    agent = CoachAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_PLAN))):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(weekly_volume_km=0.0),
        )

    assert result.confidence == pytest.approx(0.90, abs=0.01)


# ── 测试：ComplianceBlockedError 上抛 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_coach_agent_compliance_blocked_propagates():
    """call_llm 抛 ComplianceBlockedError 时应上抛给 HermesBase.run()。"""
    agent = CoachAgent(user_id=USER_ID)
    err = ComplianceBlockedError("违规内容拦截", audit=None)

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=err)):
        with pytest.raises(ComplianceBlockedError):
            await agent.execute(
                ctx=_make_ctx(),
                memory_ctx=_make_memory(),
            )


# ── 测试：LLM 异常降级 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coach_agent_llm_exception_uses_fallback():
    """call_llm 抛通用异常时，返回 fallback_plan，不崩溃。"""
    agent = CoachAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(side_effect=ConnectionError("model down"))):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(),
        )

    assert "today_plan" in result.output
    assert result.output["recovery_advice"] != ""


@pytest.mark.asyncio
async def test_coach_agent_invalid_json_uses_fallback():
    """call_llm 返回无法解析的 JSON 时使用 fallback。"""
    agent = CoachAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value="not json")):
        result = await agent.execute(
            ctx=_make_ctx(),
            memory_ctx=_make_memory(),
        )

    assert result.output is not None
    assert "today_plan" in result.output


# ── 测试：user_goal 映射 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("goal", ["减脂", "增肌", "马拉松", "体能", "健康维护"])
async def test_coach_agent_goal_focus_included_in_prompt(goal: str):
    """各 user_goal 的 goal_focus 应出现在构建的 prompt 中（验证映射正确）。"""
    expected_focus = GOAL_FOCUS_MAP[goal]
    prompt = CoachAgent._build_prompt(
        data_report=DATA_REPORT,
        sport_type="running",
        user_goal=goal,
        goal_focus=expected_focus,
        current_plan={},
        weekly_volume_km=0.0,
    )
    assert expected_focus[:10] in prompt  # 匹配前 10 字足够


# ── 测试：skill_candidates ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coach_agent_skill_candidates_sport_and_goal():
    """skill_candidates 应包含 sport_type 和 user_goal 组合标识。"""
    agent = CoachAgent(user_id=USER_ID)

    with patch.object(agent, "call_llm", new=AsyncMock(return_value=json.dumps(VALID_PLAN))):
        result = await agent.execute(
            ctx=_make_ctx(user_goal="马拉松", sport_type="trail"),
            memory_ctx=_make_memory(),
        )

    combined = " ".join(result.skill_candidates)
    assert "trail" in combined
    assert "马拉松" in combined


# ── 测试：fallback_plan 内容 ──────────────────────────────────────────────────

@pytest.mark.parametrize("sport_type,user_goal", [
    ("running", "减脂"),
    ("cycling", "增肌"),
    ("general", "健康维护"),
])
def test_fallback_plan_structure(sport_type: str, user_goal: str):
    """fallback_plan 应返回完整的 4 个字段结构。"""
    plan = CoachAgent._fallback_plan(sport_type=sport_type, user_goal=user_goal)
    assert "today_plan" in plan
    assert "weekly_load" in plan
    assert "recovery_advice" in plan
    assert "motivation" in plan
    # today_plan 内部字段完整
    tp = plan["today_plan"]
    for field in ("name", "duration_min", "distance_km", "intensity", "hr_target_zone"):
        assert field in tp
