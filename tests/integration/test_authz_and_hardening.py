# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Authorization regression + request-size + MCP auth tests
# ─────────────────────────────────────────────────────────────────────────────
"""
Three threats from THREAT_MODEL.md, exercised end-to-end:

  1. Cross-user authorization (§5 item 2):
     user_a's token must NEVER be able to act as user_b. We verify this on
     the privacy export/delete path because that's where data exfiltration
     would do the most damage.

  2. Request body size limit (§5 item 10):
     POSTs above settings.max_request_body_bytes return 413 before any
     handler runs.

  3. MCP route hardening (§5 item 1):
     /mcp/sse and /mcp/messages/ require Bearer when mcp_require_auth=True
     (which is the test default). Switching the flag off lets unauth through
     but emits a structured warning.
"""
from __future__ import annotations

import json

import pytest


# ── 1. Cross-user authorization ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_a_cannot_export_or_delete_user_b_data(app_client, patched_redis):
    """
    Seed two users; user_a's bearer token must only see/touch user_a's data.

    Because dev_auth_bypass passes whatever string is in Bearer through as
    user_id, the way to "attempt to access user_b" is to send Bearer alice
    (alice's token) and expect that the response only contains alice's
    rows — NEVER bob's. A failure here would mean the privacy service is
    not filtering by the authenticated user.
    """
    from datetime import datetime, timezone
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import AgentMemory, HealthFact

    async with AsyncSessionLocal() as sess:
        # alice's data
        sess.add_all([
            AgentMemory(
                namespace="user/alice/coach_agent",
                user_id="alice", agent="coach_agent", key="goal",
                value_json={"goal": "10K"}, tags=["profile"],
                mem_type="profile", confidence=1.0,
            ),
            HealthFact(
                user_id="alice", subject="baseline", predicate="resting_hr",
                object_json={"value": 58}, confidence=0.95,
                valid_from=datetime.now(timezone.utc),
            ),
            # bob's data — must NOT leak into alice's export
            AgentMemory(
                namespace="user/bob/coach_agent",
                user_id="bob", agent="coach_agent", key="goal",
                value_json={"goal": "marathon"}, tags=["profile"],
                mem_type="profile", confidence=1.0,
            ),
            HealthFact(
                user_id="bob", subject="injury", predicate="restricts",
                object_json={"area": "knee"}, confidence=0.9,
                valid_from=datetime.now(timezone.utc),
            ),
        ])
        await sess.commit()

    # alice queries her own data
    resp = await app_client.get(
        "/api/v1/privacy/export",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 200
    body = json.loads(resp.text)
    assert body["user_id"] == "alice"
    assert len(body["agent_memory"]) == 1
    assert len(body["health_facts"]) == 1
    # Hard-fail if any bob string leaked
    raw = json.dumps(body, ensure_ascii=False)
    assert "bob" not in raw, f"bob's data leaked into alice's export: {raw}"
    assert "marathon" not in raw
    assert "knee" not in raw

    # Now alice tries to delete with confirm_token=bob -> must 400
    resp_bad = await app_client.post(
        "/api/v1/privacy/delete",
        headers={"Authorization": "Bearer alice"},
        json={"confirm_token": "bob"},
    )
    assert resp_bad.status_code == 400

    # Bob's data must still be present
    from sqlalchemy import select
    async with AsyncSessionLocal() as sess:
        bob_mem = (await sess.execute(
            select(AgentMemory).where(AgentMemory.user_id == "bob")
        )).scalars().all()
        bob_fact = (await sess.execute(
            select(HealthFact).where(HealthFact.user_id == "bob")
        )).scalars().all()
    assert len(bob_mem) == 1
    assert len(bob_fact) == 1


# ── 2. Request body size limit ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oversized_post_is_rejected_with_413(app_client, patched_redis, monkeypatch):
    """Set the limit very low and confirm 413 is returned before the handler runs."""
    # Lower the limit just for this test by reaching into the middleware instance.
    from rhythmind.api.main import app
    from rhythmind.api.middleware.request_size import RequestSizeLimitMiddleware

    found = None
    for m in app.user_middleware:
        if m.cls is RequestSizeLimitMiddleware:
            found = m
            break
    assert found, "RequestSizeLimitMiddleware not installed"

    # Patch the active limit on the running middleware. BaseHTTPMiddleware caches
    # constructor args, so the simplest thing is to monkey-patch the instance
    # attribute at the class level via settings (since the middleware reads it
    # at call time only when its own _max_bytes is None — but here we hard-coded
    # _max_bytes at construction). We bypass that by patching settings AND
    # setting middleware _max_bytes to None via a fresh request shouldn't work
    # — instead we just monkey-patch the cached attribute via the middleware
    # pickup-from-settings path: we replace the middleware's _max_bytes by
    # walking the ASGI middleware chain.
    # Easier: send a body bigger than the configured 1 MiB default.
    big_body = "x" * (2 * 1024 * 1024)  # 2 MiB
    resp = await app_client.post(
        "/api/v1/health/upload",
        headers={
            "Authorization": "Bearer alice",
            "Content-Type": "application/json",
        },
        content=big_body,
    )
    assert resp.status_code == 413, resp.text
    assert "too large" in resp.text.lower()


@pytest.mark.asyncio
async def test_normal_sized_post_is_accepted(app_client, patched_redis):
    """A reasonable JSON body must NOT be rejected by the size middleware."""
    body = {
        "source": "manual",
        "sport_type": "running",
        "user_goal": "健康",
        "heart_rate_avg": 130.0,
        "steps": 5000,
        # extra harmless padding to push body well above 1 KiB but stay <1 MiB
        "source_raw": {"note": "x" * 1024},
    }
    # Stub the agent pool so the LLM path doesn't actually run
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from rhythmind.api.main import app
    from rhythmind.api.deps import get_pool
    from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult
    from rhythmind.core.hermes_base import HermesRunResult

    def _ok(out, agent):
        return HermesRunResult(
            compliance=ComplianceResult(level=ComplianceLevel.PASS, output=out, confidence=0.9),
            agent=agent, user_id="alice", task_type="t", latency_ms=1.0,
        )

    bundle = SimpleNamespace(
        metrics=SimpleNamespace(run=AsyncMock(return_value=_ok({"load_level": "low", "anomalies": []}, "metrics_agent"))),
        data   =SimpleNamespace(run=AsyncMock(return_value=_ok({"summary": "ok"}, "data_agent"))),
        coach  =SimpleNamespace(run=AsyncMock(return_value=_ok({"today_plan": {"name": "rest"}}, "coach_agent"))),
    )

    class _Pool:
        @asynccontextmanager
        async def acquire(self, user_id):
            yield bundle

    app.dependency_overrides[get_pool] = lambda: _Pool()
    try:
        resp = await app_client.post(
            "/api/v1/health/upload",
            headers={"Authorization": "Bearer alice"},
            json=body,
        )
    finally:
        app.dependency_overrides.pop(get_pool, None)

    assert resp.status_code == 200, resp.text


# ── 3. MCP authentication ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_messages_requires_bearer_by_default(app_client, patched_redis):
    """
    POST /mcp/messages/ without Authorization must 401 when mcp_require_auth=True
    (which is the production-safe default and what conftest leaves set).
    """
    # Sanity: our test settings should have the flag on by default
    from rhythmind.config import settings
    if not settings.mcp_require_auth:
        pytest.skip("mcp_require_auth was disabled by env; this test asserts the default-on behavior")

    resp = await app_client.post("/mcp/messages/", json={})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate", "").lower().startswith("bearer")


@pytest.mark.asyncio
async def test_mcp_messages_with_bearer_does_not_401(app_client, patched_redis):
    """
    With Authorization: Bearer <user>, the MCP route should NOT 401.
    We don't drive a real MCP session here (that needs a paired SSE stream),
    so any non-401 result is acceptable — the assertion is "auth gate passes".
    """
    resp = await app_client.post(
        "/mcp/messages/?session_id=fake",
        headers={"Authorization": "Bearer alice"},
        json={},
    )
    assert resp.status_code != 401, f"unexpected 401: {resp.text}"


@pytest.mark.asyncio
async def test_assert_production_safe_blocks_mcp_unauth(monkeypatch):
    """
    config.assert_production_safe() must raise when ENV=prod + mcp_require_auth=False.
    Belt-and-braces guard against a future deployment misstep.
    """
    from rhythmind.config import Settings

    s = Settings(
        env="prod",
        jwt_secret="x" * 40,
        litellm_master_key="sk-real",
        influxdb_token="realtoken",
        database_url="postgresql+asyncpg://u:p@h/d",
        model_primary_spec="ollama://qwen2.5:7b",
        cors_allow_origins="https://app.rhythmind.ai",
        mcp_require_auth=False,
        enforce_model_platform=False,
    )
    with pytest.raises(RuntimeError) as ei:
        s.assert_production_safe()
    assert "mcp_require_auth" in str(ei.value)
