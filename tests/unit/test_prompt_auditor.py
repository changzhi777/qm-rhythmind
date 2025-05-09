"""
tests/unit/test_prompt_auditor.py — PromptAuditor (gemma-4-e4b) 单元测试

策略：
  - 全程 mock openai.AsyncOpenAI，不依赖真实 Ollama / LiteLLM 服务
  - 测试场景：
      1. 审查器已关闭（compliance_audit_enabled=False）→ 直接 PASS
      2. overall_score < warn_score  → AuditLevel.PASS
      3. overall_score ∈ [warn, block) → AuditLevel.WARN + extra_constraints
      4. overall_score >= block_score → AuditLevel.BLOCK
      5. asyncio.TimeoutError            → 降级 PASS，auditor_available=False
      6. 网络/连接异常                   → 降级 PASS，auditor_available=False
      7. JSON 解析失败（非法 JSON）      → 降级 PASS，auditor_available=True
      8. 多模态 content（list）          → 文本提取后正常审查
      9. AuditResult 便捷属性            → blocked / warned 语义正确
     10. WARN 注入的 extra_constraints 为列表类型
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhythmind.core.compliance.prompt_auditor import (
    AuditLevel,
    AuditResult,
    PromptAuditor,
    _build_audit_prompt,
)


# ── 辅助工厂 ─────────────────────────────────────────────────────────────────

def _make_llm_response(payload: dict) -> MagicMock:
    """构造模拟的 openai ChatCompletion 响应对象。"""
    msg = MagicMock()
    msg.content = json.dumps(payload, ensure_ascii=False)

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_auditor(**overrides) -> PromptAuditor:
    """
    返回 PromptAuditor 实例，允许通过 settings mock 覆盖阈值。
    默认使用 settings 中的真实值（block=0.75, warn=0.40, timeout=8.0）。
    """
    return PromptAuditor()


_SIMPLE_MESSAGES = [
    {"role": "system", "content": "你是健康助手。"},
    {"role": "user",   "content": "帮我分析一下今天的跑步数据。"},
]


# ── 1. 审查器已关闭 ───────────────────────────────────────────────────────────

class TestAuditorDisabled:

    @pytest.mark.asyncio
    async def test_disabled_returns_pass_without_calling_llm(self):
        """compliance_audit_enabled=False 时直接返回 PASS，不调用任何 LLM。"""
        with patch("rhythmind.core.compliance.prompt_auditor.settings") as mock_settings:
            mock_settings.compliance_audit_enabled = False
            mock_settings.compliance_audit_block_score = 0.75
            mock_settings.compliance_audit_warn_score = 0.40
            mock_settings.compliance_audit_timeout = 8.0

            auditor = PromptAuditor()
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is False


# ── 公共辅助：构建 mock adapter ──────────────────────────────────────────────

def _make_adapter_mock(response_text: str) -> MagicMock:
    """返回一个 mock ModelAdapter，chat() 返回指定文本。"""
    adapter = MagicMock()
    adapter.chat = AsyncMock(return_value=response_text)
    return adapter


def _adapter_ctx(auditor: PromptAuditor, response_text: str):
    """patch auditor._get_adapter 返回 mock adapter 的 context manager。"""
    return patch.object(
        auditor, "_get_adapter",
        return_value=_make_adapter_mock(response_text),
    )


# ── 2-4. PASS / WARN / BLOCK 判定 ────────────────────────────────────────────

class TestScoringLevels:

    @pytest.mark.asyncio
    async def test_pass_score_below_warn_threshold(self):
        """overall_score=0.20 → PASS"""
        payload = {
            "medical_risk": 0.1, "privacy_risk": 0.1, "hallucination_risk": 0.1,
            "overall_score": 0.20, "reason": "正常运动数据查询", "extra_constraints": [],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.overall_score == pytest.approx(0.20)
        assert result.auditor_available is True
        assert result.blocked is False
        assert result.warned is False

    @pytest.mark.asyncio
    async def test_warn_score_between_thresholds(self):
        """overall_score=0.55 → WARN"""
        payload = {
            "medical_risk": 0.6, "privacy_risk": 0.2, "hallucination_risk": 0.3,
            "overall_score": 0.55, "reason": "涉及轻微医疗措辞",
            "extra_constraints": ["请避免使用诊断性语言", "输出应包含免责声明"],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.WARN
        assert result.overall_score == pytest.approx(0.55)
        assert result.warned is True
        assert result.blocked is False
        assert len(result.extra_constraints) == 2
        assert "免责声明" in result.extra_constraints[1]

    @pytest.mark.asyncio
    async def test_block_score_above_block_threshold(self):
        """overall_score=0.85 → BLOCK"""
        payload = {
            "medical_risk": 0.9, "privacy_risk": 0.5, "hallucination_risk": 0.8,
            "overall_score": 0.85, "reason": "要求开具处方建议", "extra_constraints": [],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.BLOCK
        assert result.blocked is True
        assert result.overall_score == pytest.approx(0.85)
        assert result.medical_risk == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_score_exactly_at_warn_boundary(self):
        """overall_score=0.40（等于 warn_score）→ WARN（含边界）"""
        payload = {
            "medical_risk": 0.4, "privacy_risk": 0.2, "hallucination_risk": 0.2,
            "overall_score": 0.40, "reason": "边界值", "extra_constraints": ["注意措辞"],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(_SIMPLE_MESSAGES)
        assert result.level == AuditLevel.WARN

    @pytest.mark.asyncio
    async def test_score_exactly_at_block_boundary(self):
        """overall_score=0.75（等于 block_score）→ BLOCK（含边界）"""
        payload = {
            "medical_risk": 0.8, "privacy_risk": 0.3, "hallucination_risk": 0.6,
            "overall_score": 0.75, "reason": "高风险边界", "extra_constraints": [],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(_SIMPLE_MESSAGES)
        assert result.level == AuditLevel.BLOCK


# ── 5-6. 降级：超时 / 连接异常 ───────────────────────────────────────────────

class TestFallbackOnUnavailability:

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_pass(self):
        """asyncio.TimeoutError → 降级 PASS，auditor_available=False，不中断主流程"""
        auditor = PromptAuditor()
        with patch.object(auditor, "_get_adapter", return_value=_make_adapter_mock("")), \
             patch("rhythmind.core.compliance.prompt_auditor.asyncio.wait_for",
                   side_effect=asyncio.TimeoutError):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is False
        assert "超时" in result.reason

    @pytest.mark.asyncio
    async def test_connection_error_falls_back_to_pass(self):
        """任意网络异常 → 降级 PASS，auditor_available=False"""
        auditor = PromptAuditor()
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(side_effect=ConnectionError("ollama unreachable"))
        with patch.object(auditor, "_get_adapter", return_value=mock_adapter):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is False
        assert "ConnectionError" in result.reason or "不可用" in result.reason

    @pytest.mark.asyncio
    async def test_generic_exception_falls_back_to_pass(self):
        """ValueError 等意外异常 → 降级 PASS，不抛出"""
        auditor = PromptAuditor()
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(side_effect=ValueError("unexpected error"))
        with patch.object(auditor, "_get_adapter", return_value=mock_adapter):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is False


# ── 7. JSON 解析失败 ─────────────────────────────────────────────────────────

class TestJsonParseFailure:

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_to_pass(self):
        """gemma 输出非法 JSON → 解析失败，降级 PASS，auditor_available=True（连接正常）"""
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, "这不是 JSON，gemma 输出了自由文本"):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.auditor_available is True   # 连接正常，只是解析出错
        assert "解析失败" in result.reason

    @pytest.mark.asyncio
    async def test_empty_json_object_is_safe(self):
        """gemma 返回空 JSON {} → 所有 risk=0.0 → PASS"""
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, "{}"):
            result = await auditor.audit(_SIMPLE_MESSAGES)

        assert result.level == AuditLevel.PASS
        assert result.overall_score == 0.0


# ── 8. 多模态 content（list 类型）────────────────────────────────────────────

class TestMultimodalContent:

    @pytest.mark.asyncio
    async def test_list_content_extracts_text_and_audits(self):
        """content 为 list（多模态）时，只提取 text 部分进行审查"""
        multimodal_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "帮我分析这张心率图"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ],
            }
        ]
        payload = {
            "medical_risk": 0.1, "privacy_risk": 0.05, "hallucination_risk": 0.05,
            "overall_score": 0.10, "reason": "正常图片分析请求", "extra_constraints": [],
        }
        auditor = PromptAuditor()
        with _adapter_ctx(auditor, json.dumps(payload)):
            result = await auditor.audit(multimodal_messages)

        assert result.level == AuditLevel.PASS


# ── 9. _build_audit_prompt 辅助函数 ──────────────────────────────────────────

class TestBuildAuditPrompt:

    def test_simple_messages_format(self):
        """正常 messages 应被正确拼接为可读文本。"""
        msgs = [
            {"role": "system", "content": "你是助手"},
            {"role": "user",   "content": "今天天气"},
        ]
        text = _build_audit_prompt(msgs)
        assert "[system]: 你是助手" in text
        assert "[user]: 今天天气" in text

    def test_long_content_is_truncated(self):
        """超过 500 字符的 content 应被截断，防止 gemma token 溢出。"""
        long_content = "x" * 1000
        msgs = [{"role": "user", "content": long_content}]
        text = _build_audit_prompt(msgs)
        # 截断后不超过 "500 + 角色前缀" 字符
        assert len(text) < 600

    def test_multimodal_list_content_extracts_text(self):
        """list 格式 content 只提取 text 部分。"""
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "分析跑步数据"},
                    {"type": "image_url", "image_url": "..."},
                ],
            }
        ]
        text = _build_audit_prompt(msgs)
        assert "分析跑步数据" in text
        # image_url 部分不应出现
        assert "image_url" not in text


# ── 10. AuditResult 便捷属性 ─────────────────────────────────────────────────

class TestAuditResultProperties:

    def test_blocked_property_true_for_block_level(self):
        r = AuditResult(level=AuditLevel.BLOCK, overall_score=0.85)
        assert r.blocked is True
        assert r.warned is False

    def test_warned_property_true_for_warn_level(self):
        r = AuditResult(level=AuditLevel.WARN, overall_score=0.55)
        assert r.warned is True
        assert r.blocked is False

    def test_neither_blocked_nor_warned_for_pass(self):
        r = AuditResult(level=AuditLevel.PASS, overall_score=0.10)
        assert r.blocked is False
        assert r.warned is False

    def test_extra_constraints_default_empty_list(self):
        r = AuditResult(level=AuditLevel.PASS)
        assert r.extra_constraints == []

    def test_auditor_available_defaults_true(self):
        r = AuditResult(level=AuditLevel.PASS)
        assert r.auditor_available is True
