"""
tests/unit/test_orchestrator_router.py — HealthRouter 意图分类与路由测试

策略：mock ComplianceGate / LoopGuard / SwarmDataCoach / Cache，
测试 HealthRouter.route() 的各个分支。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhythmind.orchestrator.router import (
    INTENT_MAP,
    INTENT_RULES,
    HealthRouter,
    WorkflowResult,
    WorkflowStatus,
)


class TestClassifyIntent:

    def test_upload_data_keywords(self):
        result = HealthRouter._classify_intent({"text": "上传garmin数据"})
        assert result == "upload_data"

    def test_set_goal_keywords(self):
        result = HealthRouter._classify_intent({"text": "我想减脂增肌"})
        assert result == "set_goal"

    def test_pain_report_keywords(self):
        result = HealthRouter._classify_intent({"text": "膝盖疼"})
        assert result == "pain_report"

    def test_vitals_alert_keywords(self):
        result = HealthRouter._classify_intent({"text": "心率异常预警"})
        assert result == "vitals_alert"

    def test_diet_query_keywords(self):
        result = HealthRouter._classify_intent({"text": "推荐低卡路里食谱"})
        assert result == "diet_query"

    def test_community_post_keywords(self):
        result = HealthRouter._classify_intent({"text": "今天打卡分享"})
        assert result == "community_post"

    def test_structured_data_fields(self):
        result = HealthRouter._classify_intent({
            "heart_rate_avg": 72,
            "steps": 8000,
        })
        assert result == "upload_data"

    def test_default_fallback(self):
        result = HealthRouter._classify_intent({"text": "你好"})
        assert result == "__default__"

    def test_mixed_keywords_first_match(self):
        result = HealthRouter._classify_intent({"text": "吃减脂目标"})
        assert result in ("diet_query", "set_goal")

    def test_case_insensitive(self):
        result = HealthRouter._classify_intent({"text": "GARMIN 同步"})
        assert result == "upload_data"


class TestIntentMap:

    def test_default_entry_exists(self):
        assert "__default__" in INTENT_MAP

    def test_all_rules_have_mapping(self):
        for keywords, intent in INTENT_RULES:
            assert intent in INTENT_MAP


class TestWorkflowResult:

    def test_blocked_factory(self):
        r = WorkflowResult.blocked("不合规", user_id="u1")
        assert r.status == WorkflowStatus.BLOCKED
        assert "不合规" in r.message
        assert r.user_id == "u1"

    def test_throttled_factory(self):
        r = WorkflowResult.throttled(user_id="u2")
        assert r.status == WorkflowStatus.THROTTLED
        assert r.user_id == "u2"

    def test_error_factory(self):
        r = WorkflowResult.error("boom", user_id="u3")
        assert r.status == WorkflowStatus.ERROR
        assert r.message == "boom"


class TestHealthRouterRoute:

    @pytest.mark.asyncio
    async def test_route_blocked_by_compliance(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=False)

        result = await router.route(user_id, {"text": "上传数据"})
        assert result.status == WorkflowStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_route_throttled_by_loop_guard(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=True)
        router.loop_guard.is_cooling_down = AsyncMock(return_value=True)

        with patch("rhythmind.orchestrator.router.IntentCache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="upload_data")
            result = await router.route(user_id, {"text": "上传数据"})

        assert result.status == WorkflowStatus.THROTTLED

    @pytest.mark.asyncio
    async def test_route_swarm_data_coach_success(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=True)
        router.loop_guard.is_cooling_down = AsyncMock(return_value=False)

        mock_swarm_result = MagicMock()
        mock_swarm_result.success = True
        mock_swarm_result.final_output = {"summary": "ok"}
        router._swarm_data_coach.run = AsyncMock(return_value=mock_swarm_result)

        with patch("rhythmind.orchestrator.router.IntentCache") as mock_cache, \
             patch("rhythmind.orchestrator.router.SessionCache") as mock_session:
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            mock_session.set = AsyncMock()
            result = await router.route(user_id, {"text": "上传garmin数据"})

        assert result.status == WorkflowStatus.SUCCESS
        assert result.data["summary"] == "ok"

    @pytest.mark.asyncio
    async def test_route_swarm_compliance_blocked(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=True)
        router.loop_guard.is_cooling_down = AsyncMock(return_value=False)

        mock_swarm_result = MagicMock()
        mock_swarm_result.success = False
        router._swarm_data_coach.run = AsyncMock(return_value=mock_swarm_result)

        with patch("rhythmind.orchestrator.router.IntentCache") as mock_cache, \
             patch("rhythmind.orchestrator.router.SessionCache") as mock_session:
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            mock_session.set = AsyncMock()
            result = await router.route(user_id, {"text": "上传数据"})

        assert result.status == WorkflowStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_route_pain_report_phase2_placeholder(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=True)
        router.loop_guard.is_cooling_down = AsyncMock(return_value=False)

        with patch("rhythmind.orchestrator.router.IntentCache") as mock_cache:
            mock_cache.get = AsyncMock(return_value="pain_report")
            result = await router.route(user_id, {"text": "膝盖疼痛"})

        assert result.status == WorkflowStatus.SUCCESS
        assert "Phase 2" in result.data["message"]

    @pytest.mark.asyncio
    async def test_route_exception_returns_error(self, user_id):
        router = HealthRouter()
        router.compliance.pre_check = MagicMock(return_value=True)
        router.loop_guard.is_cooling_down = AsyncMock(return_value=False)
        router._swarm_data_coach.run = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("rhythmind.orchestrator.router.IntentCache") as mock_cache:
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock()
            result = await router.route(user_id, {"text": "上传数据"})

        assert result.status == WorkflowStatus.ERROR
        assert "boom" in result.message
