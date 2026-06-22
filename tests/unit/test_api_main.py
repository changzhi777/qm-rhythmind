# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_api_main.py — FastAPI app 入口端点测试

覆盖 5 个 health/version 端点（line 281-400）：
- /ping / /livez / /health / /version 简单端点
- /readyz 含 DB + Redis 依赖检查（成功/失败路径）

策略：使用 FastAPI TestClient（同步 HTTP）+ patch settings + mock DB/Redis 依赖。
lifespan（line 73）不直接测——lifecycle 风险高价值低，集成测试覆盖更合适。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rhythmind.api import main as main_mod
from rhythmind.api.main import app


@pytest.fixture
def client():
    """FastAPI TestClient 包装（同步）。"""
    return TestClient(app)


class TestPing:
    """/ping 端点：返 {status, env}。"""

    def test_ping_returns_status_and_env(self, client):
        with patch.object(main_mod.settings, "env", "dev"):
            resp = client.get("/ping")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["env"] == "dev"


class TestLivez:
    """/livez 端点：K8s livenessProbe，返 {status, version}。"""

    def test_livez_returns_alive_with_version(self, client):
        resp = client.get("/livez")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "alive"
        assert "version" in body


class TestHealth:
    """/health 端点：兼容旧 LB，=livez。"""

    def test_health_returns_healthy_with_version(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "version" in body


class TestVersion:
    """/version 端点：返 version + git_sha + build_time。"""

    def test_version_returns_metadata(self, client, monkeypatch):
        """version 端点：返 version + git_sha + build_time（环境变量）。"""
        monkeypatch.setenv("RHYTHMIND_GIT_SHA", "abc123")
        monkeypatch.setenv("RHYTHMIND_BUILD_TIME", "2026-06-15T10:00:00Z")

        resp = client.get("/version")
        assert resp.status_code == 200
        body = resp.json()
        assert "version" in body
        assert body["git_sha"] == "abc123"
        assert body["build_time"] == "2026-06-15T10:00:00Z"

    def test_version_returns_unknown_when_env_unset(self, client, monkeypatch):
        """环境变量未注入时返 'unknown'（本地启动场景）。"""
        monkeypatch.delenv("RHYTHMIND_GIT_SHA", raising=False)
        monkeypatch.delenv("RHYTHMIND_BUILD_TIME", raising=False)

        resp = client.get("/version")
        assert resp.status_code == 200
        body = resp.json()
        assert body["git_sha"] == "unknown"
        assert body["build_time"] == "unknown"


class TestReadyz:
    """/readyz 端点：K8s readinessProbe，检查 DB + Redis 依赖。"""

    def test_readyz_200_when_all_deps_ok(self, client, monkeypatch):
        """DB + Redis 都可达时返 200 + status=ok。"""
        # DB 成功（AsyncSessionLocal context manager 返回 mock session）
        @pytest.fixture
        def mock_sess_ok():
            sess = AsyncMock()
            sess.__aenter__ = AsyncMock(return_value=sess)
            sess.__aexit__ = AsyncMock(return_value=False)
            sess.execute = AsyncMock(return_value=MagicMock())
            return sess

        # mock redis：ping 成功
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        # mock AsyncSessionLocal（line 300）和 redis.asyncio.from_url（line 312）
        # AsyncSessionLocal 必须是 async context manager factory
        @pytest.fixture
        def session_factory(sess):
            @staticmethod
            def factory():
                class _CM:
                    async def __aenter__(self_inner):
                        return sess
                    async def __aexit__(self_inner, *exc):
                        return False
                return _CM()
            return factory
        # 直接 patch AsyncSessionLocal 和 redis.asyncio.from_url
        monkeypatch.setattr(
            "rhythmind.core.memory.manager.AsyncSessionLocal",
            lambda: _make_session_cm(),
        )
        # skip LLM upstream check（默认关闭；用 readyz_check_llm_upstream=False）
        monkeypatch.setattr(main_mod.settings, "readyz_check_llm_upstream", False)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            resp = client.get("/readyz")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["checks"]["db"] == "ok"
        assert body["checks"]["redis"] == "ok"

    def test_readyz_503_when_db_unavailable(self, client, monkeypatch):
        """DB 不可达时返 503 + checks.db=fail。"""
        # mock AsyncSessionLocal 抛异常
        @pytest.fixture
        def raise_db_error():
            class _CM:
                async def __aenter__(self_inner):
                    raise ConnectionRefusedError("db down")
                async def __aexit__(self_inner, *exc):
                    return False
            return lambda: _CM()
        # mock 抛异常的 session factory
        class _CM:
            def __init__(self):
                self._raise = True
            async def __aenter__(self_inner):
                raise ConnectionRefusedError("db down")
            async def __aexit__(self_inner, *exc):
                return False
        monkeypatch.setattr(
            "rhythmind.core.memory.manager.AsyncSessionLocal",
            lambda: _CM(),
        )
        # Redis mock 成功（不让 redis 也失败，否则无法定位 db 失败）
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        monkeypatch.setattr(main_mod.settings, "readyz_check_llm_upstream", False)

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            resp = client.get("/readyz")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "not_ready"
        assert "fail" in body["checks"]["db"]


def _make_session_cm():
    """构造一个 AsyncSessionLocal context manager（用于 readyz 成功路径 mock）。"""
    class _CM:
        async def __aenter__(inner):
            sess = AsyncMock()
            sess.execute = AsyncMock(return_value=MagicMock())
            return sess

        async def __aexit__(inner, *exc):
            return False

    return _CM()
