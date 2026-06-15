"""
tests/unit/test_api_deps.py — FastAPI 依赖注入测试

覆盖：JWT 解析（dev bypass + 标准 JWT）、get_router / get_pool 单例。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import rhythmind.api.deps as deps
from rhythmind.api.deps import get_current_user_id, get_pool, get_router

TEST_JWT_SECRET = "test-secret-32-chars-minimum-length!"


class TestDevAuthBypass:

    @pytest.mark.asyncio
    async def test_dev_bypass_returns_plain_token(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "env", "dev")
        monkeypatch.setattr(settings, "dev_auth_bypass", True)

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="alice",
        )
        user_id = await get_current_user_id(creds)
        assert user_id == "alice"

    @pytest.mark.asyncio
    async def test_dev_bypass_rejected_in_prod_env(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "env", "prod")
        monkeypatch.setattr(settings, "dev_auth_bypass", True)

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="alice",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(creds)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_dev_bypass_rejected_when_disabled(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "env", "dev")
        monkeypatch.setattr(settings, "dev_auth_bypass", False)

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="alice",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(creds)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_dev_bypass_skipped_for_jwt_format(self, monkeypatch):
        """以 eyJ 开头的 token 即使在 dev bypass 模式也走 JWT 解析。"""
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "env", "dev")
        monkeypatch.setattr(settings, "dev_auth_bypass", True)
        monkeypatch.setattr(settings, "jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256")

        # Fake JWT-looking token (will fail JWT decode)
        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="eyJhbGciOiJIUzI1NiJ9.bogus.payload",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(creds)
        assert "Token validation failed" in exc_info.value.detail


class TestJWTValidation:

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_user_id(self, monkeypatch):
        from jose import jwt as jose_jwt

        from rhythmind.config import settings
        monkeypatch.setattr(settings, "jwt_secret", TEST_JWT_SECRET)
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256")

        token = jose_jwt.encode(
            {"sub": "user42"}, TEST_JWT_SECRET, algorithm="HS256"
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        user_id = await get_current_user_id(creds)
        assert user_id == "user42"

    @pytest.mark.asyncio
    async def test_invalid_jwt_raises_401(self, monkeypatch):
        from rhythmind.config import settings
        monkeypatch.setattr(settings, "jwt_secret", "test-secret")
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256")

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="eyJhbGciOiJIUzI1NiJ9.invalid.payload",
        )
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(creds)
        assert exc_info.value.status_code == 401
        assert "Token validation failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_jwt_missing_sub_raises_401(self, monkeypatch):
        from jose import jwt as jose_jwt

        from rhythmind.config import settings
        monkeypatch.setattr(settings, "jwt_secret", TEST_JWT_SECRET)
        monkeypatch.setattr(settings, "jwt_algorithm", "HS256")

        token = jose_jwt.encode(
            {"no_sub": "here"}, TEST_JWT_SECRET, algorithm="HS256"
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(creds)
        assert "missing sub" in exc_info.value.detail


class TestSingletons:

    def test_get_router_returns_same_instance(self, monkeypatch):
        monkeypatch.setattr(deps, "_router_instance", None)
        r1 = get_router()
        r2 = get_router()
        assert r1 is r2

    def test_get_pool_returns_agent_pool(self):
        pool = get_pool()
        assert pool is not None
        assert hasattr(pool, "acquire")
