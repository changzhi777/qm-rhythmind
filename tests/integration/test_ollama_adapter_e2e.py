# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Integration test: real OllamaAdapter through AdapterRouter,
# mocking the upstream Ollama HTTP server with pytest-httpx.
# ─────────────────────────────────────────────────────────────────────────────
"""
This test exercises:
  - AdapterRouter.chat() — the real router, including the Prometheus埋点
  - OllamaAdapter — the real adapter using openai.AsyncOpenAI under the hood
  - HTTP layer — mocked via pytest-httpx so we don't need a running Ollama

What we assert:
  - The mocked /v1/chat/completions endpoint was hit
  - The response text comes back through the router untouched
  - rhythmind_llm_calls_total{adapter="ollama",result="success"} incremented
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_ollama_path_through_adapter_router(httpx_mock):
    """
    Full LLM path: AdapterRouter → OllamaAdapter → openai SDK → httpx → mocked Ollama.
    """
    # 1) Stub the Ollama OpenAI-compat endpoint
    httpx_mock.add_response(
        url="http://stub-ollama:11434/v1/chat/completions",
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
                    "message": {"role": "assistant", "content": "ok-from-ollama"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
        },
    )

    # 2) Drive the real router with an ollama:// spec
    from rhythmind.adapters.adapter_router import AdapterRouter
    from rhythmind.adapters.ollama_adapter import _CLIENT_CACHE, OllamaAdapter

    # Force a fresh OllamaAdapter pointed at our stub host
    _CLIENT_CACHE.clear()
    router = AdapterRouter()
    # Inject an instance so the router doesn't rebuild from settings
    router._instances["ollama://qwen2.5:7b"] = OllamaAdapter(
        "qwen2.5:7b",
        base_url="http://stub-ollama:11434",
        timeout=5.0,
    )

    # 3) Snapshot metric before
    from rhythmind.observability import LLM_CALLS
    before = _counter_value(LLM_CALLS, ("ollama", "success"))

    text = await router.chat(
        messages=[{"role": "user", "content": "ping"}],
        model_spec="ollama://qwen2.5:7b",
        temperature=0.1,
        max_tokens=8,
    )

    # 4) Assertions
    assert text == "ok-from-ollama"
    assert len(httpx_mock.get_requests()) == 1
    posted = httpx_mock.get_requests()[0]
    body = json.loads(posted.read())
    assert body["model"] == "qwen2.5:7b"
    assert body["messages"][0]["content"] == "ping"

    after = _counter_value(LLM_CALLS, ("ollama", "success"))
    assert after - before == 1, "LLM success counter should have incremented exactly once"


@pytest.mark.asyncio
async def test_ollama_error_increments_error_counter(httpx_mock):
    """Upstream 500 should propagate and bump the error counter."""
    # openai SDK retries 5xx by default — mark response as reusable.
    httpx_mock.add_response(
        url="http://stub-ollama:11434/v1/chat/completions",
        method="POST",
        status_code=500,
        json={"error": {"message": "boom"}},
        is_reusable=True,
    )

    from rhythmind.adapters.adapter_router import AdapterRouter
    from rhythmind.adapters.ollama_adapter import _CLIENT_CACHE, OllamaAdapter
    from rhythmind.observability import LLM_CALLS

    _CLIENT_CACHE.clear()
    router = AdapterRouter()
    router._instances["ollama://broken"] = OllamaAdapter(
        "broken", base_url="http://stub-ollama:11434", timeout=5.0,
    )

    before = _counter_value(LLM_CALLS, ("ollama", "error"))

    with pytest.raises(Exception):
        await router.chat(
            messages=[{"role": "user", "content": "x"}],
            model_spec="ollama://broken",
        )

    after = _counter_value(LLM_CALLS, ("ollama", "error"))
    assert after - before == 1


# ── helpers ─────────────────────────────────────────────────────────────────

def _counter_value(counter, labels: tuple[str, ...]) -> float:
    """Return current counter value for a given label set; 0 if未初始化."""
    try:
        # prometheus_client Counter.labels(...).get() doesn't exist; use _value
        sample = counter.labels(*labels)._value.get()  # noqa: SLF001
        return float(sample)
    except Exception:
        return 0.0
