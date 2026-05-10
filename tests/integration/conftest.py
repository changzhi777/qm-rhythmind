# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Integration test fixtures
# ─────────────────────────────────────────────────────────────────────────────
"""
Integration tests target the real FastAPI application stack:
  - Real router + dependency injection
  - Real HermesBase pipeline (mocked LLM only)
  - In-memory SQLite via existing tests/conftest.py reset_db fixture
  - fakeredis to back LoopGuard + rate-limit + readyz check

Anything beyond the API/orchestration layer (LLMs, QMD, Influx) is mocked
so the suite runs offline in CI in <10 s.
"""
from __future__ import annotations

import os

# 必须在 import rhythmind 之前注入 env。
# 用 dict 赋值（非 setdefault）强制覆盖 CI / 本地 shell 的 ENV=test，
# 因为 dev_auth_bypass 依赖 settings.env == "dev"。
os.environ["ENV"] = "dev"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "integration-test-secret-32-chars-min!")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-integration-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")
os.environ.setdefault("MODEL_PRIMARY_SPEC", "ollama://stub")
os.environ.setdefault("COMPLIANCE_AUDIT_ENABLED", "false")  # 跳过 prompt audit

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def patched_redis(monkeypatch):
    """把 rate_limit + LoopGuard 的 redis.from_url 换成 fakeredis。"""
    import fakeredis.aioredis as fake_aioredis

    fake = fake_aioredis.FakeRedis(decode_responses=True)

    def _from_url(*args, **kwargs):
        return fake

    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", _from_url, raising=True)

    # 强制重建 rate_limit 模块持有的连接
    import rhythmind.api.rate_limit as rl
    rl._redis_client = None  # type: ignore[attr-defined]

    yield fake

    await fake.flushdb()
    await fake.aclose()


@pytest_asyncio.fixture
async def app_client(patched_redis):
    """返回一个绑定到 FastAPI app 的 AsyncClient。"""
    from rhythmind.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
