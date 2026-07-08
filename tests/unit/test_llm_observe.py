# ruff: noqa: ANN001, ANN002, ANN003, ANN201, ANN202
"""
tests/unit/test_llm_observe.py — LLM 观测模块单元测试

覆盖：
  - @observe_llm 装饰器（正常/no-op/token 估算）
  - SuggestionEngine（5 条规则）
  - init_langfuse（启用/禁用/缺 key）
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from rhythmind.observability.llm_observe import (
    _estimate_cost,
    _estimate_tokens,
    init_langfuse,
    observe_llm,
)
from rhythmind.observability.suggestion_engine import (
    ModelMetrics,
    generate_suggestions,
)

# ── @observe_llm 装饰器 ────────────────────────────────────────────────


class TestObserveLLMDecorator:

    @pytest.mark.asyncio
    async def test_disabled_returns_directly(self):
        """Langfuse 禁用时装饰器透传，不调用 Langfuse。"""
        with patch(
            "rhythmind.observability.llm_observe.get_langfuse",
            return_value=None,
        ):
            @observe_llm(model="test", agent="test")
            async def my_func(messages):
                return "result"

            result = await my_func(messages=[{"role": "user", "content": "hi"}])
            assert result == "result"

    @pytest.mark.asyncio
    async def test_enabled_captures_result(self):
        """Langfuse 启用时自动创建 trace 和 generation。"""
        mock_trace = MagicMock()
        mock_gen = MagicMock()
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.generation.return_value = mock_gen

        with patch(
            "rhythmind.observability.llm_observe.get_langfuse",
            return_value=mock_client,
        ):
            @observe_llm(model="gpt-4o", agent="coach")
            async def my_func(messages, temperature=0.3, max_tokens=1024):
                return "AI response"

            result = await my_func(
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.5,
                max_tokens=2048,
            )

            assert result == "AI response"
            mock_client.trace.assert_called_once()
            mock_trace.generation.assert_called_once()
            mock_gen.end.assert_called_once()
            mock_client.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_still_records(self):
        """LLM 调用异常时仍然记录到 Langfuse。"""
        mock_trace = MagicMock()
        mock_gen = MagicMock()
        mock_client = MagicMock()
        mock_client.trace.return_value = mock_trace
        mock_trace.generation.return_value = mock_gen

        with patch(
            "rhythmind.observability.llm_observe.get_langfuse",
            return_value=mock_client,
        ):
            @observe_llm(model="test", agent="test")
            async def failing_func(messages):
                raise RuntimeError("timeout")

            with pytest.raises(RuntimeError, match="timeout"):
                await failing_func(messages=[])

            mock_gen.end.assert_called_once()
            call_kwargs = mock_gen.end.call_args[1]
            assert call_kwargs["level"] == "ERROR"


# ── Token/Cost 估算 ────────────────────────────────────────────────────


class TestEstimation:

    def test_estimate_tokens_basic(self):
        kwargs = {"messages": [
            {"role": "user", "content": "Hello world"},
        ]}
        tokens = _estimate_tokens(kwargs, "This is a test response")
        assert tokens > 0

    def test_estimate_tokens_empty(self):
        tokens = _estimate_tokens({}, None)
        assert tokens == 0

    def test_estimate_cost_known_model(self):
        # 2026-07-08: _estimate_cost 返回 float 而非 dict
        cost = _estimate_cost(
            "gpt-4o",
            {"messages": [{"role": "user", "content": "hi"}]},
            "ok",
        )
        assert cost > 0

    def test_estimate_cost_free_model(self):
        cost = _estimate_cost("gemma-4-e4b-it", {"messages": []}, "ok")
        assert cost == 0.0

    def test_estimate_cost_unknown_model(self):
        cost = _estimate_cost("unknown-model", {"messages": [
            {"role": "user", "content": "x" * 100},
        ]}, "y" * 50)
        assert cost > 0


# ── init_langfuse ──────────────────────────────────────────────────────


class TestInitLangfuse:

    def test_disabled_returns_false(self):
        with patch("rhythmind.config.settings") as mock_s:
            mock_s.langfuse_enabled = False
            assert init_langfuse() is False

    def test_missing_keys_returns_false(self):
        with patch("rhythmind.config.settings") as mock_s:
            mock_s.langfuse_enabled = True
            mock_s.langfuse_public_key = ""
            mock_s.langfuse_secret_key = ""
            assert init_langfuse() is False

    def test_success_initializes_client(self, monkeypatch):
        """line 39-50: 配置完整 + langfuse 导入成功 → 创建 Langfuse 客户端 + 返 True。"""
        from rhythmind.observability import llm_observe

        # 重置 _langfuse_client（避免其他测试残留）
        monkeypatch.setattr(llm_observe, "_langfuse_client", None)

        # mock settings + langfuse.Langfuse
        mock_settings = MagicMock()
        mock_settings.langfuse_enabled = True
        mock_settings.langfuse_public_key = "pk-test"
        mock_settings.langfuse_secret_key = "sk-test"
        mock_settings.langfuse_host = "https://langfuse.test"
        monkeypatch.setattr("rhythmind.config.settings", mock_settings)

        mock_langfuse_module = MagicMock()
        mock_langfuse_instance = MagicMock()
        mock_langfuse_module.Langfuse = MagicMock(return_value=mock_langfuse_instance)
        monkeypatch.setitem(sys.modules, "langfuse", mock_langfuse_module)

        result = llm_observe.init_langfuse()

        assert result is True
        mock_langfuse_module.Langfuse.assert_called_once_with(
            public_key="pk-test",
            secret_key="sk-test",
            host="https://langfuse.test",
        )
        # 全局 _langfuse_client 被设置
        assert llm_observe._langfuse_client is mock_langfuse_instance

    def test_exception_during_init_returns_false(self, monkeypatch):
        """line 51-54: Langfuse 构造抛异常 → logger.error + 清空 _langfuse_client + 返 False。"""
        from rhythmind.observability import llm_observe

        # 预置一个伪 client（验证异常路径会清空）
        monkeypatch.setattr(llm_observe, "_langfuse_client", "stale_client")

        mock_settings = MagicMock()
        mock_settings.langfuse_enabled = True
        mock_settings.langfuse_public_key = "pk-test"
        mock_settings.langfuse_secret_key = "sk-test"
        mock_settings.langfuse_host = "https://langfuse.test"
        monkeypatch.setattr("rhythmind.config.settings", mock_settings)

        # mock langfuse 抛出 RuntimeError
        mock_langfuse_module = MagicMock()
        mock_langfuse_module.Langfuse = MagicMock(side_effect=RuntimeError("network unreachable"))
        monkeypatch.setitem(sys.modules, "langfuse", mock_langfuse_module)

        result = llm_observe.init_langfuse()

        assert result is False
        # _langfuse_client 被清空（不是 stale_client）
        assert llm_observe._langfuse_client is None


# ── SuggestionEngine ───────────────────────────────────────────────────


def _make_model(**overrides) -> ModelMetrics:
    defaults = dict(
        model="test-model",
        total_calls=100,
        success_calls=100,
        avg_latency_ms=500.0,
        p95_latency_ms=800.0,
        total_tokens=10000,
        total_cost=0.5,
        output_input_ratio=0.3,
    )
    defaults.update(overrides)
    return ModelMetrics(**defaults)


class TestSuggestionEngine:

    def test_no_suggestions_when_healthy(self):
        models = [_make_model()]
        suggestions = generate_suggestions(models)
        assert len(suggestions) == 0

    def test_high_latency_triggers_suggestion(self):
        models = [
            _make_model(model="fast-a", avg_latency_ms=100),
            _make_model(model="fast-b", avg_latency_ms=150),
            _make_model(model="slow", avg_latency_ms=5000),
        ]
        suggestions = generate_suggestions(models)
        assert any("延迟偏高" in s.title for s in suggestions)

    def test_low_token_ratio_triggers_suggestion(self):
        models = [_make_model(output_input_ratio=0.03, total_calls=20)]
        suggestions = generate_suggestions(models)
        assert any("Token" in s.title for s in suggestions)

    def test_high_error_rate_triggers_suggestion(self):
        models = [_make_model(total_calls=100, success_calls=90)]
        suggestions = generate_suggestions(models)
        assert any("错误率" in s.title for s in suggestions)

    def test_weekly_cost_spike_triggers_suggestion(self):
        models = [_make_model()]
        suggestions = generate_suggestions(models, week_over_week_cost_delta=0.5)
        assert any("成本" in s.title for s in suggestions)

    def test_repeated_prompts_triggers_suggestion(self):
        models = [_make_model()]
        suggestions = generate_suggestions(models, repeated_prompt_count=50)
        assert any("重复" in s.title for s in suggestions)

    def test_empty_models_returns_empty(self):
        assert generate_suggestions([]) == []
