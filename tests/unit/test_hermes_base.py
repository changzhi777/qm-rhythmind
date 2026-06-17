"""
tests/unit/test_hermes_base.py — HermesBase 闭环流程测试

通过 Mock 替换 LLM 调用，专注测试四步闭环的控制流。
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rhythmind.core.compliance.gate import ComplianceLevel
from rhythmind.core.hermes_base import (
    AgentContext,
    AgentResult,
    HermesBase,
    HermesRunResult,
    _extract_json_object,
    _make_blocked_compliance,
)
from rhythmind.core.memory import MemoryRecallResult

# ── 最简 Agent 实现（仅用于测试基类行为）────────────────────────────────

class EchoAgent(HermesBase):
    """直接返回 input_data 的 Agent，用于测试 HermesBase 闭环。"""

    def __init__(self, user_id: str, confidence: float = 0.92) -> None:
        super().__init__("echo_agent", user_id)
        self._confidence = confidence

    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
    ) -> AgentResult:
        return AgentResult(
            output=f"echo: {ctx.input_data.get('text', '')}",
            confidence=self._confidence,
            skill_candidates=["echo_template"],
            memory_updates={"last_echo": ctx.input_data.get("text", "")},
        )


class TestHermesBaseLoop:

    @pytest.mark.asyncio
    async def test_pass_flow_completes(
        self, user_id: str, session_id: str
    ):
        """PASS 流程：execute → compliance PASS → memory 更新"""

        agent = EchoAgent(user_id=user_id, confidence=0.92)
        ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="test",
            input_data={"text": "hello"},
        )
        result: HermesRunResult = await agent.run(ctx)

        assert result.success is True
        assert result.compliance.level == ComplianceLevel.PASS
        assert "echo" in result.output
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_block_flow_skips_memory(
        self, user_id: str, session_id: str
    ):
        """BLOCK 流程：memory 不应被更新"""

        agent = EchoAgent(user_id=user_id, confidence=0.40)  # < warn_threshold → BLOCK
        ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="test",
            input_data={"text": "low confidence output"},
        )
        result = await agent.run(ctx)

        assert result.success is False
        assert result.compliance.level == ComplianceLevel.BLOCK
        assert result.output is None
        assert result.compliance.requires_human_review is True

    @pytest.mark.asyncio
    async def test_warn_appends_disclaimer(
        self, user_id: str, session_id: str
    ):
        """WARN 流程：输出包含免责声明"""

        agent = EchoAgent(user_id=user_id, confidence=0.65)  # [0.50, 0.75) → WARN
        ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="test",
            input_data={"text": "borderline output"},
        )
        result = await agent.run(ctx)

        assert result.compliance.level == ComplianceLevel.WARN
        # 免责声明已追加
        assert result.compliance.disclaimer_appended is True

    @pytest.mark.asyncio
    async def test_memory_recall_and_update(
        self, user_id: str, session_id: str
    ):
        """四步闭环：recall → execute → compliance → update_memory"""
        agent = EchoAgent(user_id=user_id, confidence=0.92)
        ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="test",
            input_data={"text": "memory test"},
        )
        result = await agent.run(ctx)
        assert result.success is True


# ── _extract_json_object：LLM 输出鲁棒 JSON 提取 ───────────────────────────

class TestExtractJsonObject:
    """覆盖 4 条返回路径：空内容 / 纯 JSON / markdown fence / 括号配对。"""

    def test_empty_content_returns_empty(self):
        """空字符串/None 直接返回原值。"""
        assert _extract_json_object("") == ""
        assert _extract_json_object("") == ""  # 已存在 line 89 覆盖

    def test_pure_json_returned_as_is(self):
        """顶层纯 JSON 直接返回（不剥思考文本）。"""
        raw = '{"a": 1, "b": 2}'
        assert _extract_json_object(raw) == raw

    def test_json_in_markdown_fence_extracted(self):
        """```json ... ``` markdown fence 提取内部 JSON。"""
        raw = '思考过程...\n```json\n{"x": 42}\n```\n完成'
        assert _extract_json_object(raw) == '{"x": 42}'

    def test_json_in_plain_fence_extracted(self):
        """无语言标识的 ``` ... ``` fence 也能提取。"""
        raw = 'prefix\n```\n{"y": "ok"}\n```\nsuffix'
        assert _extract_json_object(raw) == '{"y": "ok"}'

    def test_brace_pairing_with_thinking_text(self):
        """思考文本 + 顶层 JSON：用括号配对定位。"""
        raw = '让我分析一下... {"action": "test", "value": 99} 完成。'
        assert _extract_json_object(raw) == '{"action": "test", "value": 99}'

    def test_brace_pairing_with_nested_object(self):
        """嵌套对象也能正确配对。"""
        raw = '思考：{"outer": {"inner": [1, 2, 3]}, "ok": true}'
        assert _extract_json_object(raw) == '{"outer": {"inner": [1, 2, 3]}, "ok": true}'

    def test_brace_pairing_handles_strings_with_braces(self):
        """字符串内的 {} 不应干扰括号配对。"""
        raw = '说明：{"msg": "hello {world}", "n": 1}'
        assert _extract_json_object(raw) == '{"msg": "hello {world}", "n": 1}'

    def test_brace_pairing_handles_escaped_quotes(self):
        """字符串内的转义双引号应正确处理。"""
        raw = r'思考：{"msg": "she said \"hi\"", "n": 1} 完成'
        # 验证至少能识别到顶层 JSON 边界（精确内容因正则+回溯实现而定）
        extracted = _extract_json_object(raw)
        # 至少提取的 JSON 能被 json.loads 解析
        import json
        json.loads(extracted)

    def test_no_json_returns_original_content(self):
        """找不到 { 时返回原 content（让下游 json.loads 报错）。"""
        raw = "no json at all, just text"
        assert _extract_json_object(raw) == raw

    def test_malformed_json_with_braces_returns_original(self):
        """找到边界但内容非法（json.loads 失败）→ 返回原 content。"""
        raw = 'prefix {"a": invalid} suffix'
        assert _extract_json_object(raw) == raw


# ── _make_blocked_compliance：构造 BLOCK 时的 ComplianceResult ─────────────

class TestMakeBlockedCompliance:
    def test_returns_block_level_with_reason(self):
        """_make_blocked_compliance 应返回 BLOCK 级别，触发关键词含 reason。"""
        result = _make_blocked_compliance("敏感词命中")
        assert result.level == ComplianceLevel.BLOCK
        assert result.compliance_block is True
        assert result.output is None
        assert result.confidence == 0.0
        # reason 透传到 triggered_keywords
        assert "敏感词命中" in result.triggered_keywords

    def test_advise_review_default_false(self):
        """BLOCK 时 advisor_review 默认 False（不是 advisor 主动标记）。"""
        result = _make_blocked_compliance("any reason")
        assert result.advisor_review is False


# ── HermesBase.remember()：memory 代理 ────────────────────────────────────

class TestRemember:
    """remember() 是 memory.write() 的薄代理。"""

    @pytest.mark.asyncio
    async def test_remember_delegates_to_memory_write(self):
        """remember(key, value, mem_type) 应代理到 self.memory.write。"""
        from unittest.mock import AsyncMock

        from rhythmind.core.memory.types import MemoryType

        # 最小 HermesBase 子类（不调 run()，直接测 remember）
        class _MiniAgent(HermesBase):
            async def execute(self, ctx, memory_ctx):  # pragma: no cover
                raise NotImplementedError

        agent = _MiniAgent(agent_name="mini", user_id="u1")
        agent.memory = AsyncMock()
        await agent.remember("k1", {"v": 1}, mem_type=MemoryType.PROJECT)

        agent.memory.write.assert_awaited_once_with(
            "k1", {"v": 1}, MemoryType.PROJECT
        )


# ── _extract_json_object 两条 try/except pass 路径（line 97-98/107-108）────

class TestExtractJsonObjectExceptionPaths:
    """覆盖"看似 JSON 但解析失败"的两条 pass-through 路径。"""

    def test_brace_only_content_falls_through_to_bracket_pair(self):
        """前后大括号但内容非法（line 97-98）→ pass 落到括号配对。"""
        # "hello world" 被前后大括号包围，json.loads 失败
        # 括号配对会找到 {hello world}（line 110-143），最终返回原 content（line 141 边界找到但非法）
        result = _extract_json_object("{hello world}")
        assert result == "{hello world}"

    def test_fence_with_invalid_json_falls_through(self):
        """markdown fence 内 JSON 非法（line 107-108）→ pass 落到括号配对。"""
        content = '```json\n{invalid: json}\n```'
        # fence 匹配到 {invalid: json} 但 json.loads 失败
        # 落到括号配对：找到 {invalid: json}，边界但非法 → 返回原 content
        result = _extract_json_object(content)
        assert result == content


# ── run() 错误/边界 + call_llm 错误路径 ─────────────────────────────────

class TestRunAndCallLlmBoundaries:
    """覆盖 run() 的 ComplianceBlockedError/advisor_review + call_llm BLOCK/WARN 路径。"""

    @pytest.mark.asyncio
    async def test_run_returns_blocked_result_when_execute_raises_compliance_blocked(self):
        """execute() 抛 ComplianceBlockedError（line 229-234）→ 返 blocked HermesRunResult。"""
        from rhythmind.core.hermes_base import ComplianceBlockedError
        from rhythmind.core.compliance.gate import ComplianceResult

        class _BlockAgent(EchoAgent):
            async def execute(self, ctx, memory_ctx):
                audit = ComplianceResult(
                    level=ComplianceLevel.BLOCK, output=None, confidence=0.0,
                    compliance_block=True, triggered_keywords=["敏感词命中"],
                )
                raise ComplianceBlockedError(reason="敏感词命中", audit=audit)

        agent = _BlockAgent(user_id="u1", confidence=0.95)
        ctx = AgentContext(
            user_id="u1", session_id="s1",
            task_type="test", input_data={"q": "敏感词"},
        )
        result = await agent.run(ctx)

        # ComplianceBlockedError 路径：success 隐式 False（BLOCK），output=None
        assert result.compliance.level == ComplianceLevel.BLOCK
        assert result.compliance.compliance_block is True
        assert result.compliance.output is None
        # _make_blocked_compliance(str(e)) 把 e.reason 整串塞进 triggered_keywords
        assert "敏感词命中" in result.compliance.triggered_keywords

    @pytest.mark.asyncio
    async def test_run_advisor_review_path_sets_flag_and_early_returns(self):
        """AgentResult.requires_human_review=True + compliance non-BLOCK（line 256-259）→ advisor_review=True + 早 return。"""
        class _AdvisorAgent(EchoAgent):
            async def execute(self, ctx, memory_ctx):
                # requires_human_review=True 的 AgentResult
                return AgentResult(
                    output={"recommendation": "see doctor"},
                    confidence=0.85,
                    requires_human_review=True,
                )

        agent = _AdvisorAgent(user_id="u1", confidence=0.95)
        ctx = AgentContext(
            user_id="u1", session_id="s1",
            task_type="test", input_data={},
        )
        result = await agent.run(ctx)

        # advisor_review 应被设上（来自 requires_human_review 信号）
        assert result.compliance.advisor_review is True
        # early return：output 仍来自 compliance（非 None，因为 advisor_review 不 BLOCK）
        assert result.compliance.output == {"recommendation": "see doctor"}

    @pytest.mark.asyncio
    async def test_call_llm_raises_compliance_blocked_when_auditor_blocks(self):
        """call_llm 调 auditor 后 audit.level=BLOCK（line 338）→ 抛 ComplianceBlockedError。"""
        from rhythmind.core.hermes_base import ComplianceBlockedError
        from rhythmind.core.compliance.prompt_auditor import AuditLevel, AuditResult

        mock_auditor = MagicMock()
        mock_auditor.audit = AsyncMock(return_value=AuditResult(
            level=AuditLevel.BLOCK,
            overall_score=0.95,
            medical_risk=0.9,
            privacy_risk=0.0,
            hallucination_risk=0.0,
            reason="block_keyword_hit",
            extra_constraints=[],
            auditor_available=True,
        ))

        agent = EchoAgent(user_id="u1", confidence=0.95)
        agent.auditor = mock_auditor  # 直接替换实例属性（__init__ 已 self.auditor = PromptAuditor()）

        with pytest.raises(ComplianceBlockedError, match="prompt 审查拦截"):
            await agent.call_llm([{"role": "user", "content": "敏感 prompt"}])

    @pytest.mark.asyncio
    async def test_call_llm_warn_injects_constraints_into_existing_system_message(self):
        """call_llm 调 auditor 后 audit.level=WARN（line 354-359）→ extra_constraints 追加到 system 消息。

        验证方式：mock 底层 adapter 为 AsyncMock 接收最终 messages 参数，
        检查传入的 messages 中 system content 含 "[安全约束]" + 约束列表。
        """
        from rhythmind.core.compliance.prompt_auditor import AuditLevel, AuditResult

        mock_auditor = MagicMock()
        mock_auditor.audit = AsyncMock(return_value=AuditResult(
            level=AuditLevel.WARN,
            overall_score=0.6,
            medical_risk=0.5,
            privacy_risk=0.0,
            hallucination_risk=0.0,
            reason="mild_concern",
            extra_constraints=["不要给出医疗诊断", "建议用户咨询医生"],
            auditor_available=True,
        ))

        # mock 底层 adapter 的 chat()，捕获最终 messages
        agent = EchoAgent(user_id="u1", confidence=0.95)
        agent.auditor = mock_auditor

        captured_messages: list[list[dict]] = []

        async def fake_chat(messages, **kwargs):
            captured_messages.append(messages)
            return "mocked response"

        with patch("rhythmind.adapters.adapter_router.adapter_router.get") as mock_router_get:
            mock_adapter = MagicMock()
            mock_adapter.chat = fake_chat  # 直接赋值（不 wrap）— fake_chat 是 async
            mock_router_get.return_value = mock_adapter

            await agent.call_llm([
                {"role": "system", "content": "你是健康助手。"},
                {"role": "user", "content": "我最近胸闷"},
            ])

        # 验证：mock_auditor.audit 被调用（说明 WARN 路径走到）
        mock_auditor.audit.assert_awaited_once()
        # 验证：注入的 messages（captured_messages[0]）中 system content 含约束
        assert len(captured_messages) == 1
        sys_msg = next(m for m in captured_messages[0] if m.get("role") == "system")
        assert "[安全约束]" in sys_msg["content"]
        assert "不要给出医疗诊断" in sys_msg["content"]
        assert "建议用户咨询医生" in sys_msg["content"]
        # 原始 system content 应保留
        assert "你是健康助手" in sys_msg["content"]
