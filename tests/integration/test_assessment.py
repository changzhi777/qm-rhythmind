"""
tests/integration/test_assessment.py — 跨领域评估 API 专项测试 (2026-07-08)

覆盖 3 端点 + fallback 路径:
  POST /api/v1/assessment/start     — 启动 + 计算缺失维度
  POST /api/v1/assessment/question  — 出题(LLM 失败用 fallback 题库)
  POST /api/v1/assessment/complete  — 3 维评分 + 入库

数据模型: 3 本国家职业技能标准 (康复 + 营养 + 运动)
"""
from __future__ import annotations

import os

# 必须在 import rhythmind 之前注入 env
os.environ["ENV"] = "dev"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "integration-test-asmt-secret!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-asmt-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("MODEL_PRIMARY_SPEC", "ollama://stub")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")

import pytest

# Fixtures: auth_headers / app_client 由 conftest.py 提供


# ── /start 端点 ─────────────────────────────────────────────────────────


class TestAssessmentStart:
    @pytest.mark.asyncio
    async def test_returns_session_and_dimensions(self, app_client, auth_headers):
        """无数据时返回 3 个待评估维度。"""
        resp = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "session_id" in body
        assert body["missing_dimensions"] == ["rehab", "nutrition", "training"]
        assert isinstance(body["current_state"], dict)

    @pytest.mark.asyncio
    async def test_unauthorized(self, app_client):
        """无 Bearer 时返回 401/403。"""
        resp = await app_client.post("/api/v1/assessment/start")
        assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_session_id_is_uuid(self, app_client, auth_headers):
        """session_id 应为合法 UUID 格式。"""
        import uuid

        resp = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        body = resp.json()
        # 不抛异常即合法 UUID
        uuid.UUID(body["session_id"])


# ── /question 端点 ───────────────────────────────────────────────────────


class TestAssessmentQuestion:
    @pytest.mark.asyncio
    async def test_first_question_rehab(self, app_client, auth_headers):
        """启动 → 问 rehab 第 1 题,返回题目。"""
        start = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        sid = start.json()["session_id"]

        resp = await app_client.post(
            "/api/v1/assessment/question",
            json={"session_id": sid, "answer": "", "dimension": "rehab"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "question" in body
        assert isinstance(body["question"], str)
        assert body["dimension"] == "rehab"
        assert "is_final" in body

    @pytest.mark.asyncio
    async def test_invalid_dimension(self, app_client, auth_headers):
        """无效 dimension 返回 400。"""
        start = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        sid = start.json()["session_id"]

        resp = await app_client.post(
            "/api/v1/assessment/question",
            json={"session_id": sid, "answer": "", "dimension": "invalid"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_session_not_found(self, app_client, auth_headers):
        """不存在的 session 返回 404。"""
        resp = await app_client.post(
            "/api/v1/assessment/question",
            json={"session_id": "nonexistent-id", "answer": "", "dimension": "rehab"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_after_three_questions_is_final(self, app_client, auth_headers):
        """答 3 题后第 4 个问题是 final=True。"""
        start = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        sid = start.json()["session_id"]

        for i in range(3):
            r = await app_client.post(
                "/api/v1/assessment/question",
                json={"session_id": sid, "answer": "A", "dimension": "rehab"},
                headers=auth_headers,
            )
            assert r.status_code == 200
        # 第 4 个问题应是 final
        r4 = await app_client.post(
            "/api/v1/assessment/question",
            json={"session_id": sid, "answer": "A", "dimension": "rehab"},
            headers=auth_headers,
        )
        assert r4.json()["is_final"] is True


# ── /complete 端点 ───────────────────────────────────────────────────────


class TestAssessmentComplete:
    @pytest.mark.asyncio
    async def test_fallback_scores_structure(self, app_client, auth_headers):
        """complete 返回 3 维分数 + advice + summary。"""
        start = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        sid = start.json()["session_id"]
        # 答 3 题
        for _ in range(3):
            await app_client.post(
                "/api/v1/assessment/question",
                json={"session_id": sid, "answer": "A. 没有", "dimension": "rehab"},
                headers=auth_headers,
            )
        # 完成
        resp = await app_client.post(
            "/api/v1/assessment/complete",
            json={"session_id": sid, "force": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        # scores
        for dim in ("rehab", "nutrition", "training"):
            assert dim in body["scores"]
            assert 0 <= body["scores"][dim] <= 100
        # advice
        assert isinstance(body["advice"], str)
        assert "康复" in body["advice"]
        # summary
        assert "levels" in body["summary"]
        assert "total_questions" in body["summary"]
        assert "evaluated_at" in body["summary"]

    @pytest.mark.asyncio
    async def test_session_not_found_complete(self, app_client, auth_headers):
        """不存在的 session complete 返回 404。"""
        resp = await app_client.post(
            "/api/v1/assessment/complete",
            json={"session_id": "nonexistent-id", "force": False},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_after_complete_returns_404(self, app_client, auth_headers):
        """完成 2 次(session 已删除)返回 404。"""
        start = await app_client.post(
            "/api/v1/assessment/start", headers=auth_headers
        )
        sid = start.json()["session_id"]
        for _ in range(3):
            await app_client.post(
                "/api/v1/assessment/question",
                json={"session_id": sid, "answer": "A", "dimension": "rehab"},
                headers=auth_headers,
            )
        r1 = await app_client.post(
            "/api/v1/assessment/complete",
            json={"session_id": sid, "force": True},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        r2 = await app_client.post(
            "/api/v1/assessment/complete",
            json={"session_id": sid, "force": True},
            headers=auth_headers,
        )
        assert r2.status_code == 404
