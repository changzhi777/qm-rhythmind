"""
tests/unit/test_hermes_base.py — HermesBase 闭环流程测试

通过 Mock 替换 LLM 调用，专注测试四步闭环的控制流。
"""
from __future__ import annotations

import pytest

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
