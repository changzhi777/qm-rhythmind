# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Privacy endpoints (GDPR/PIPL) integration tests
# ─────────────────────────────────────────────────────────────────────────────
"""
Covers the /api/v1/privacy/* surface end-to-end:

  GET  /privacy/export   — auth required, returns JSON with all user-tagged data
  POST /privacy/delete   — confirm_token must == user_id; cascades all stores
  GET  /privacy/policy   — public-ish info, but still under auth in our setup
"""
from __future__ import annotations

import json

import pytest

USER = "alice"
HEADERS = {"Authorization": f"Bearer {USER}"}


async def _seed_user_data(user_id: str) -> tuple[int, int]:
    """直接写两条 AgentMemory + 一条 HealthFact，模拟该用户已经使用过系统。"""
    from datetime import datetime, timezone
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import AgentMemory, HealthFact

    async with AsyncSessionLocal() as sess:
        sess.add_all([
            AgentMemory(
                namespace=f"user/{user_id}/metrics_agent",
                user_id=user_id,
                agent="metrics_agent",
                key="last_run",
                value_json={"hr": 145},
                tags=["session"],
                mem_type="session",
                confidence=0.9,
            ),
            AgentMemory(
                namespace=f"user/{user_id}/coach_agent",
                user_id=user_id,
                agent="coach_agent",
                key="goal",
                value_json={"goal": "10K"},
                tags=["profile"],
                mem_type="profile",
                confidence=1.0,
            ),
            HealthFact(
                user_id=user_id,
                subject="baseline",
                predicate="resting_hr",
                object_json={"value": 58},
                confidence=0.95,
                valid_from=datetime.now(timezone.utc),
            ),
        ])
        await sess.commit()
    return (2, 1)


@pytest.mark.asyncio
async def test_export_returns_user_data_as_json(app_client, patched_redis):
    mem, fact = await _seed_user_data(USER)

    resp = await app_client.get("/api/v1/privacy/export", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]

    body = json.loads(resp.text)
    assert body["user_id"] == USER
    assert body["schema_version"] == "1.0"
    assert len(body["agent_memory"]) == mem
    assert len(body["health_facts"]) == fact
    # redis_keys 应该是空（fakeredis 默认空），但字段应存在
    assert isinstance(body["redis_keys"], list)


@pytest.mark.asyncio
async def test_export_requires_auth(app_client, patched_redis):
    resp = await app_client.get("/api/v1/privacy/export")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_delete_rejects_wrong_confirm_token(app_client, patched_redis):
    await _seed_user_data(USER)
    resp = await app_client.post(
        "/api/v1/privacy/delete",
        headers=HEADERS,
        json={"confirm_token": "not-alice"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_purges_pg_and_redis_and_returns_report(app_client, patched_redis):
    # Seed PG
    await _seed_user_data(USER)
    # Seed Redis with user-scoped keys
    await patched_redis.set(f"loop:{USER}:rehab", "1")
    await patched_redis.set(f"rl:user:upload:{USER}", "5")
    await patched_redis.set(f"session:{USER}:abc", "x")
    # Seed an unrelated user's keys to ensure they survive
    await patched_redis.set("loop:bob:rehab", "1")

    resp = await app_client.post(
        "/api/v1/privacy/delete",
        headers=HEADERS,
        json={"confirm_token": USER},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_id"] == USER

    # Find each store's outcome
    outcomes = {s["store"]: s["detail"] for s in body["successes"]}
    assert "agent_memory" in outcomes
    assert outcomes["agent_memory"].endswith("2 rows")
    assert "health_fact" in outcomes
    assert outcomes["health_fact"].endswith("1 rows")
    assert "redis" in outcomes
    # 3 seeded + at least 1 rate-limit counter created by this very call.
    # rate-limit key matches `rl:user:*:{user_id}` pattern and so it's correctly
    # reaped — but it means the count is ≥ 3, not exactly 3.
    import re
    m = re.search(r"deleted (\d+) keys", outcomes["redis"])
    assert m and int(m.group(1)) >= 3

    # Bob's key still there
    assert await patched_redis.get("loop:bob:rehab") == "1"
    # Alice's PG rows really gone
    from sqlalchemy import select
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import AgentMemory, HealthFact
    async with AsyncSessionLocal() as sess:
        rem_mem = (await sess.execute(select(AgentMemory).where(AgentMemory.user_id == USER))).scalars().all()
        rem_fact = (await sess.execute(select(HealthFact).where(HealthFact.user_id == USER))).scalars().all()
    assert rem_mem == [] and rem_fact == []


@pytest.mark.asyncio
async def test_policy_endpoint_returns_static_info(app_client, patched_redis):
    resp = await app_client.get("/api/v1/privacy/policy", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["policy_url"].startswith("https://")
    assert "@" in body["contact_email"]
    assert body["last_updated"]
