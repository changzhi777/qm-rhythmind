# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Integration test: real OMLXAdapter through AdapterRouter,
# mocking the upstream oMLX HTTP server with pytest-httpx.
# ─────────────────────────────────────────────────────────────────────────────
"""
This test exercises:
  - AdapterRouter.chat() — the real router, including the Prometheus 埋点
  - OMLXAdapter — the real adapter using openai.AsyncOpenAI under the hood
  - HTTP layer — mocked via pytest-httpx so we don't need a running oMLX

What we assert:
  - The mocked /v1/chat/completions endpoint was hit
  - The response text comes back through the router untouched
  - rhythmind_llm_calls_total{adapter="omlX",result="success"} incremented
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_omlX_path_through_adapter_router(httpx_mock):
    """
    Full LLM path: AdapterRouter → OMLXAdapter → openai SDK → httpx → mocked oMLX.
    """
    # 1) Stub the oMLX OpenAI-compat endpoint
    httpx_mock.add_response(
        url="http://stub-omlX:11434/v1/chat/completions",
        method="POST",
        status_code=200,
        json={
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": 0,
            "model": "qwen2.5:7b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok-from-omlX"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    )

    # 2) Drive the real router with an omlX:// spec
    from rhythmind.adapters.adapter_router import AdapterRouter
    from rhythmind.adapters.omlX_adapter import _CLIENT_CACHE, OMLXAdapter

    # Force a fresh OMLXAdapter pointed at our stub host
    _CLIENT_CACHE.clear()
    router = AdapterRouter()
    # Inject an instance so the router doesn't rebuild from settings
    router._instances["omlX://qwen2.5:7b"] = OMLXAdapter(
        "qwen2.5:7b",
        base_url="http://stub-omlX:11434",
        api_key="test-key",
        timeout=5.0,
    )

    # 3) Snapshot metric before
    from rhythmind.observability import LLM_CALLS
    before = _counter_value(LLM_CALLS, ("omlX", "success"))

    text = await router.chat(
        messages=[{"role": "user", "content": "ping"}],
        model_spec="omlX://qwen2.5:7b",
        temperature=0.1,
        max_tokens=8,
    )

    # 4) Assertions
    assert text == "ok-from-omlX"
    assert len(httpx_mock.get_requests()) == 1
    posted = httpx_mock.get_requests()[0]
    body = json.loads(posted.read())
    assert body["model"] == "qwen2.5:7b"
    assert body["messages"][0]["content"] == "ping"

    # 5) Metrics — only meaningful when prometheus_client is available
    from rhythmind.observability import metrics as obs_metrics
    if obs_metrics._PROMETHEUS_AVAILABLE:
        after = _counter_value(LLM_CALLS, ("omlX", "success"))
        assert after - before == 1, "LLM success counter should have incremented exactly once"  # noqa: E501


@pytest.mark.asyncio
async def test_omlX_error_increments_error_counter(httpx_mock):
    """Upstream 500 should propagate and bump the error counter."""
    # openai SDK retries 5xx by default — mark response as reusable.
    httpx_mock.add_response(
        url="http://stub-omlX:11434/v1/chat/completions",
        method="POST",
        status_code=500,
        json={"error": {"message": "boom"}},
        is_reusable=True,
    )

    from rhythmind.adapters.adapter_router import AdapterRouter
    from rhythmind.adapters.omlX_adapter import _CLIENT_CACHE, OMLXAdapter
    from rhythmind.observability import LLM_CALLS
    from rhythmind.observability import metrics as obs_metrics

    _CLIENT_CACHE.clear()
    # Inject no-retry client to avoid SDK's default 2 retries on 5xx
    from openai import AsyncOpenAI
    _CLIENT_CACHE["http://stub-omlX:11434"] = AsyncOpenAI(
        base_url="http://stub-omlX:11434/v1",
        api_key="test-key",
        max_retries=0,
    )
    router = AdapterRouter()
    router._instances["omlX://broken"] = OMLXAdapter(
        "broken", base_url="http://stub-omlX:11434", api_key="test-key", timeout=5.0,
    )

    before = _counter_value(LLM_CALLS, ("omlX", "error"))

    with pytest.raises(Exception):
        await router.chat(
            messages=[{"role": "user", "content": "x"}],
            model_spec="omlX://broken",
        )

    if obs_metrics._PROMETHEUS_AVAILABLE:
        after = _counter_value(LLM_CALLS, ("omlX", "error"))
        assert after - before == 1


# ── helpers ─────────────────────────────────────────────────────────────────

def _counter_value(counter, labels: tuple[str, ...]) -> float:
    """Return current counter value for a given label set; 0 if未初始化."""
    try:
        sample = counter.labels(*labels)._value.get()  # noqa: SLF001
        return float(sample)
    except Exception:
        return 0.0
