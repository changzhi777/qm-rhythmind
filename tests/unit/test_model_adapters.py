"""
tests/unit/test_model_adapters.py — Model Adapter 层单元测试

策略：
  - MLXAdapter   → mock mlx_lm.load / mlx_lm.generate（不需要真实 GPU）
  - OllamaAdapter → mock openai.AsyncOpenAI（不需要真实 Ollama）
  - LiteLLMAdapter→ mock openai.AsyncOpenAI（不需要真实 LiteLLM）
  - AdapterRouter → 验证路由逻辑 + 缓存 + chat() 委托

测试覆盖：
  1. 各 Adapter 正常 chat() 路径
  2. Adapter.model_id 格式
  3. MLXAdapter thinking 模式控制（enable_thinking 参数 + 标签剥离）
  4. MLXAdapter 模型缓存（同 path 只 load 一次）
  5. OllamaAdapter health_check
  6. AdapterRouter 前缀路由（mlx:// / ollama:// / 其他）
  7. AdapterRouter 实例缓存（同 spec 返回同一实例）
  8. AdapterRouter.chat() 默认使用 settings.model_primary_spec
  9. PromptAuditor 切换到 OllamaAdapter 路径
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── 清理全局缓存，保证测试隔离 ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_adapter_caches():
    """每个测试前清空 AdapterRouter 缓存 + MLX 模型缓存。"""
    from rhythmind.adapters import adapter_router
    from rhythmind.adapters import mlx_adapter as mlx_mod

    adapter_router.clear_cache()
    mlx_mod._MODEL_CACHE.clear()
    mlx_mod._MLX_SEMAPHORE = None
    yield
    adapter_router.clear_cache()
    mlx_mod._MODEL_CACHE.clear()
    mlx_mod._MLX_SEMAPHORE = None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ModelAdapter ABC
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelAdapterABC:

    def test_cannot_instantiate_directly(self):
        from rhythmind.adapters.model_adapter import ModelAdapter
        with pytest.raises(TypeError):
            ModelAdapter()  # type: ignore[abstract]

    def test_stream_default_delegates_to_chat(self):
        """stream() 默认实现调一次 chat() 后 yield。"""
        from rhythmind.adapters.model_adapter import ModelAdapter

        class ConcreteAdapter(ModelAdapter):
            @property
            def model_id(self): return "test"
            async def chat(self, messages, **kwargs): return "hello"

        async def run():
            adapter = ConcreteAdapter()
            results = []
            async for chunk in adapter.stream([{"role": "user", "content": "hi"}]):
                results.append(chunk)
            return results

        results = asyncio.get_event_loop().run_until_complete(run())
        assert results == ["hello"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. MLXAdapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestMLXAdapter:

    def _make_mock_tokenizer(self, support_thinking: bool = True):
        tok = MagicMock()
        if support_thinking:
            tok.apply_chat_template.side_effect = lambda msgs, **kw: (
                f"<think_mode={'on' if kw.get('enable_thinking') else 'off'}>"
                + msgs[-1]["content"]
            )
        else:
            # TypeError when enable_thinking passed (old tokenizer)
            def _apply(msgs, **kw):
                if "enable_thinking" in kw:
                    raise TypeError("unexpected kwarg")
                return msgs[-1]["content"]
            tok.apply_chat_template.side_effect = _apply
        return tok

    @pytest.mark.asyncio
    async def test_model_id_format(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter
        a = MLXAdapter("mlx-community/Qwen3-30B-A3B-4bit")
        assert a.model_id == "mlx://mlx-community/Qwen3-30B-A3B-4bit"

    @pytest.mark.asyncio
    async def test_chat_calls_generate_and_returns_text(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter, _MODEL_CACHE

        mock_model = MagicMock()
        mock_tok = self._make_mock_tokenizer()

        with patch("rhythmind.adapters.mlx_adapter.MLXAdapter._load",
                   return_value=(mock_model, mock_tok)), \
             patch("rhythmind.adapters.mlx_adapter.generate",
                   return_value="生成的回答") as mock_gen:

            adapter = MLXAdapter("mlx-community/Qwen3-30B-A3B-4bit")
            result = await adapter.chat(
                [{"role": "user", "content": "你好"}],
                temperature=0.3,
                max_tokens=512,
            )

        assert result == "生成的回答"
        mock_gen.assert_called_once()

    @pytest.mark.asyncio
    async def test_thinking_mode_off_strips_think_tags(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter

        mock_tok = self._make_mock_tokenizer()

        with patch("rhythmind.adapters.mlx_adapter.MLXAdapter._load",
                   return_value=(MagicMock(), mock_tok)), \
             patch("rhythmind.adapters.mlx_adapter.generate",
                   return_value="<think>内部推理过程</think>最终答案"):

            adapter = MLXAdapter("test-model", thinking=False)
            result = await adapter.chat([{"role": "user", "content": "test"}])

        assert "<think>" not in result
        assert result == "最终答案"

    @pytest.mark.asyncio
    async def test_thinking_mode_on_preserves_think_tags(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter

        mock_tok = self._make_mock_tokenizer()

        with patch("rhythmind.adapters.mlx_adapter.MLXAdapter._load",
                   return_value=(MagicMock(), mock_tok)), \
             patch("rhythmind.adapters.mlx_adapter.generate",
                   return_value="<think>推理过程</think>结论"):

            adapter = MLXAdapter("test-model", thinking=True)
            result = await adapter.chat([{"role": "user", "content": "test"}])

        assert "<think>" in result

    @pytest.mark.asyncio
    async def test_tokenizer_fallback_no_thinking_support(self):
        """老版 tokenizer 不支持 enable_thinking → fallback /no_think 前缀。"""
        from rhythmind.adapters.mlx_adapter import MLXAdapter

        mock_tok = self._make_mock_tokenizer(support_thinking=False)

        with patch("rhythmind.adapters.mlx_adapter.MLXAdapter._load",
                   return_value=(MagicMock(), mock_tok)), \
             patch("rhythmind.adapters.mlx_adapter.generate",
                   return_value="回答") as mock_gen:

            adapter = MLXAdapter("test-model", thinking=False)
            await adapter.chat([{"role": "user", "content": "test"}])

        # generate 被调用，且 prompt 包含 /no_think 前缀
        call_kwargs = mock_gen.call_args
        prompt = call_kwargs.args[2] if len(call_kwargs.args) > 2 else call_kwargs.kwargs.get("prompt", "")
        assert "/no_think" in prompt

    @pytest.mark.asyncio
    async def test_model_cached_after_first_load(self):
        """同一 model_path 只调用 mlx_lm.load 一次。"""
        from rhythmind.adapters.mlx_adapter import MLXAdapter

        mock_tok = self._make_mock_tokenizer()

        with patch("rhythmind.adapters.mlx_adapter.load",
                   return_value=(MagicMock(), mock_tok)) as mock_load, \
             patch("rhythmind.adapters.mlx_adapter.generate", return_value="ok"):

            adapter = MLXAdapter("same-model")
            await adapter.chat([{"role": "user", "content": "1"}])
            await adapter.chat([{"role": "user", "content": "2"}])

        assert mock_load.call_count == 1  # 只加载一次

    @pytest.mark.asyncio
    async def test_health_check_true_when_mlx_installed(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter
        import rhythmind.adapters.mlx_adapter as mlx_mod
        # load 已是模块级变量，直接 patch
        with patch.object(mlx_mod, "load", MagicMock()):
            adapter = MLXAdapter("test")
            ok = await adapter.health_check()
        assert ok is True

    @pytest.mark.asyncio
    async def test_health_check_false_when_mlx_missing(self):
        from rhythmind.adapters.mlx_adapter import MLXAdapter
        import rhythmind.adapters.mlx_adapter as mlx_mod
        with patch.object(mlx_mod, "load", None):
            adapter = MLXAdapter("test")
            ok = await adapter.health_check()
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# 3. OllamaAdapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestOllamaAdapter:

    def _mock_ollama_response(self, text: str):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = text
        resp.usage = MagicMock()
        resp.usage.total_tokens = 100
        return resp

    @pytest.mark.asyncio
    async def test_model_id_format(self):
        from rhythmind.adapters.ollama_adapter import OllamaAdapter
        a = OllamaAdapter("gemma3:4b")
        assert a.model_id == "ollama://gemma3:4b"

    @pytest.mark.asyncio
    async def test_chat_returns_response(self):
        from rhythmind.adapters.ollama_adapter import OllamaAdapter, _CLIENT_CACHE
        _CLIENT_CACHE.clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._mock_ollama_response("审查通过")
        )

        with patch("rhythmind.adapters.ollama_adapter._get_client",
                   return_value=mock_client):
            adapter = OllamaAdapter("gemma3:4b")
            result = await adapter.chat(
                [{"role": "user", "content": "请审查"}],
                temperature=0.1,
                max_tokens=512,
                response_format={"type": "json_object"},
            )

        assert result == "审查通过"

    @pytest.mark.asyncio
    async def test_health_check_ok(self):
        from rhythmind.adapters.ollama_adapter import OllamaAdapter
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_resp))
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            adapter = OllamaAdapter("gemma3:4b")
            ok = await adapter.health_check()

        assert ok is True

    @pytest.mark.asyncio
    async def test_health_check_fail_on_connection_error(self):
        from rhythmind.adapters.ollama_adapter import OllamaAdapter

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("connection refused")
            )
            adapter = OllamaAdapter("gemma3:4b")
            ok = await adapter.health_check()

        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LiteLLMAdapter
# ═══════════════════════════════════════════════════════════════════════════════

class TestLiteLLMAdapter:

    def _mock_litellm_response(self, text: str):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = text
        resp.usage = MagicMock()
        resp.usage.total_tokens = 200
        return resp

    @pytest.mark.asyncio
    async def test_model_id_is_spec(self):
        from rhythmind.adapters.litellm_adapter import LiteLLMAdapter
        a = LiteLLMAdapter("primary")
        assert a.model_id == "primary"

    @pytest.mark.asyncio
    async def test_chat_passes_model_spec(self):
        from rhythmind.adapters.litellm_adapter import LiteLLMAdapter, _CLIENT_CACHE
        _CLIENT_CACHE.clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._mock_litellm_response("LLM 响应")
        )

        with patch("rhythmind.adapters.litellm_adapter._get_client",
                   return_value=mock_client):
            adapter = LiteLLMAdapter("primary")
            result = await adapter.chat(
                [{"role": "user", "content": "你好"}],
                temperature=0.5,
                max_tokens=1024,
            )

        assert result == "LLM 响应"
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "primary"
        assert call_kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_response_format_forwarded(self):
        from rhythmind.adapters.litellm_adapter import LiteLLMAdapter, _CLIENT_CACHE
        _CLIENT_CACHE.clear()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=self._mock_litellm_response('{"result": "ok"}')
        )

        with patch("rhythmind.adapters.litellm_adapter._get_client",
                   return_value=mock_client):
            adapter = LiteLLMAdapter("primary")
            await adapter.chat(
                [{"role": "user", "content": "json"}],
                response_format={"type": "json_object"},
            )

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs.get("response_format") == {"type": "json_object"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. AdapterRouter
# ═══════════════════════════════════════════════════════════════════════════════

class TestAdapterRouter:

    @pytest.fixture
    def router(self):
        from rhythmind.adapters.adapter_router import AdapterRouter
        return AdapterRouter()

    def test_mlx_prefix_creates_mlx_adapter(self, router):
        from rhythmind.adapters.mlx_adapter import MLXAdapter
        a = router.get("mlx://mlx-community/Qwen3-30B-A3B-4bit")
        assert isinstance(a, MLXAdapter)

    def test_ollama_prefix_creates_ollama_adapter(self, router):
        from rhythmind.adapters.ollama_adapter import OllamaAdapter
        a = router.get("ollama://gemma3:4b")
        assert isinstance(a, OllamaAdapter)

    def test_plain_string_creates_litellm_adapter(self, router):
        from rhythmind.adapters.litellm_adapter import LiteLLMAdapter
        for spec in ["primary", "fast", "anthropic/claude-3-7-sonnet-20250219"]:
            a = router.get(spec)
            assert isinstance(a, LiteLLMAdapter)

    def test_same_spec_returns_same_instance(self, router):
        a1 = router.get("ollama://gemma3:4b")
        a2 = router.get("ollama://gemma3:4b")
        assert a1 is a2

    def test_different_specs_return_different_instances(self, router):
        a1 = router.get("ollama://gemma3:4b")
        a2 = router.get("ollama://llama3:8b")
        assert a1 is not a2

    def test_clear_cache_resets_instances(self, router):
        a1 = router.get("ollama://gemma3:4b")
        router.clear_cache()
        a2 = router.get("ollama://gemma3:4b")
        assert a1 is not a2

    @pytest.mark.asyncio
    async def test_chat_delegates_to_adapter(self, router):
        """router.chat() 应正确委托到底层 Adapter.chat()。"""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value="路由响应")

        with patch.object(router, "get", return_value=mock_adapter):
            result = await router.chat(
                [{"role": "user", "content": "test"}],
                model_spec="ollama://gemma3:4b",
            )

        assert result == "路由响应"
        mock_adapter.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chat_uses_primary_spec_when_no_model_spec(self, router):
        """model_spec=None 时应使用 settings.model_primary_spec。"""
        import rhythmind.adapters.adapter_router as router_mod

        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value="默认响应")

        captured_spec: list[str] = []

        def fake_get(spec: str):
            captured_spec.append(spec)
            return mock_adapter

        mock_settings = MagicMock()
        mock_settings.model_primary_spec = "mlx://mlx-community/Qwen3-30B-A3B-4bit"
        mock_settings.model_primary = "primary"

        with patch.object(router, "get", side_effect=fake_get), \
             patch.object(router_mod, "settings", mock_settings, create=True):
            # adapter_router.chat() 内部 `from rhythmind.config import settings`
            # 要 patch 的是 rhythmind.config.settings
            pass

        # 换用更直接的方式：patch rhythmind.config.settings
        with patch("rhythmind.config.settings") as mock_cfg, \
             patch.object(router, "get", side_effect=fake_get):
            mock_cfg.model_primary_spec = "mlx://mlx-community/Qwen3-30B-A3B-4bit"
            mock_cfg.model_primary = "primary"
            await router.chat([{"role": "user", "content": "hi"}])

        assert captured_spec[0] == "mlx://mlx-community/Qwen3-30B-A3B-4bit"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PromptAuditor 使用 OllamaAdapter 路径
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptAuditorWithAdapter:

    @pytest.mark.asyncio
    async def test_auditor_uses_adapter_router(self):
        """PromptAuditor.audit() 应通过 AdapterRouter 调用 OllamaAdapter，而非直接 AsyncOpenAI。"""
        from rhythmind.core.compliance.prompt_auditor import PromptAuditor

        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value='{"overall_score": 0.1, "medical_risk": 0.0, "privacy_risk": 0.0, "hallucination_risk": 0.0, "reason": "安全", "extra_constraints": []}')

        auditor = PromptAuditor(model_spec="ollama://gemma3:4b")

        with patch.object(auditor, "_get_adapter", return_value=mock_adapter):
            result = await auditor.audit([{"role": "user", "content": "今天跑步了"}])

        from rhythmind.core.compliance.prompt_auditor import AuditLevel
        assert result.level == AuditLevel.PASS
        mock_adapter.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auditor_model_spec_from_settings(self):
        """model_spec=None 时应读 settings.model_compliance_spec。"""
        with patch("rhythmind.core.compliance.prompt_auditor.settings") as mock_settings:
            mock_settings.compliance_audit_enabled = False
            mock_settings.compliance_audit_block_score = 0.75
            mock_settings.compliance_audit_warn_score = 0.40
            mock_settings.compliance_audit_timeout = 8.0
            mock_settings.model_compliance_spec = "ollama://custom-gemma:latest"
            mock_settings.model_compliance = "compliance"

            from rhythmind.core.compliance.prompt_auditor import PromptAuditor
            auditor = PromptAuditor()
            assert auditor._model_spec == "ollama://custom-gemma:latest"

    @pytest.mark.asyncio
    async def test_auditor_timeout_fallback(self):
        """Adapter 超时时降级返回 PASS。"""
        from rhythmind.core.compliance.prompt_auditor import AuditLevel, PromptAuditor

        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(side_effect=asyncio.TimeoutError())

        auditor = PromptAuditor(model_spec="ollama://gemma3:4b")
        with patch.object(auditor, "_get_adapter", return_value=mock_adapter):
            result = await auditor.audit([{"role": "user", "content": "test"}])

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is False
