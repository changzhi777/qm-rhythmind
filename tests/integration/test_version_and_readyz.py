# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — /version + extended /readyz integration tests (P8)
# ─────────────────────────────────────────────────────────────────────────────
"""
Covers two small but ops-critical surfaces:

  1. GET /version returns version + git_sha + build_time + env. Falls back
     to "unknown" when the build args weren't injected (i.e. local dev).

  2. GET /readyz with readyz_check_llm_upstream=True actually pings
     LiteLLM and Ollama; if both unreachable the response is 503.
"""
from __future__ import annotations

import os

import pytest


@pytest.mark.asyncio
async def test_version_endpoint_default(app_client, patched_redis):
    resp = await app_client.get("/version")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body["version"]                # non-empty
    # build args not injected in test → unknown
    assert body["git_sha"] == "unknown"
    assert body["build_time"] == "unknown"
    assert "env" in body


@pytest.mark.asyncio
async def test_version_picks_up_build_args(app_client, patched_redis, monkeypatch):
    monkeypatch.setenv("RHYTHMIND_GIT_SHA", "deadbeef0123456789")
    monkeypatch.setenv("RHYTHMIND_BUILD_TIME", "2026-05-09T12:34:56Z")

    resp = await app_client.get("/version")
    body = resp.json()
    assert body["git_sha"].startswith("deadbeef")
    assert body["build_time"].startswith("2026-")


@pytest.mark.asyncio
async def test_readyz_with_llm_upstream_disabled_skips_those_checks(
    app_client, patched_redis,
):
    """Default behavior: readyz_check_llm_upstream=False → only db+redis."""
    resp = await app_client.get("/readyz")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    assert "db" in checks and "redis" in checks
    assert "litellm" not in checks
    assert "ollama" not in checks


@pytest.mark.asyncio
async def test_readyz_with_upstream_check_returns_503_when_both_fail(
    app_client, patched_redis, monkeypatch,
):
    """
    Enable upstream check; both endpoints will fail (no real LiteLLM/Ollama
    available in test) → readyz must return 503 with the failure reasons.
    """
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "readyz_check_llm_upstream", True)
    monkeypatch.setattr(settings, "readyz_llm_timeout", 0.1)

    resp = await app_client.get("/readyz")
    body = resp.json()
    checks = body["checks"]
    assert "litellm" in checks
    assert "ollama" in checks
    # Both should be failures (we have no servers running in the test env)
    assert checks["litellm"].startswith("fail")
    assert checks["ollama"].startswith("fail")
    assert resp.status_code == 503
    assert body["status"] == "not_ready"


@pytest.mark.asyncio
async def test_readyz_with_only_one_upstream_failing_still_ready(
    app_client, patched_redis, monkeypatch, httpx_mock,
):
    """
    If only one of LiteLLM / Ollama is reachable, readyz stays ready
    (the adapter router can still route). Only when BOTH fail do we 503.
    """
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "readyz_check_llm_upstream", True)
    monkeypatch.setattr(settings, "readyz_llm_timeout", 0.5)

    # LiteLLM responds OK; Ollama responds 500 → adapter sees failure
    httpx_mock.add_response(
        url=f"{settings.litellm_url}/health",
        method="GET",
        status_code=200,
        json={"status": "ok"},
    )
    httpx_mock.add_response(
        url=f"{settings.ollama_base_url}/api/tags",
        method="GET",
        status_code=500,
    )

    resp = await app_client.get("/readyz")
    body = resp.json()
    checks = body["checks"]
    assert checks["litellm"] == "ok"
    assert checks["ollama"].startswith("fail")
    # 单挂仍 200 — adapter_router 可走 LiteLLM
    assert resp.status_code == 200
