"""
tests/unit/test_hermes_base.py — HermesBase 闭环流程测试

通过 Mock 替换 LLM 调用，专注测试四步闭环的控制流。
"""
from __future__ import annotations

from typing import Any

import pytest

from rhythmind.core.compliance.gate import ComplianceLevel
from rhythmind.core.hermes_base import (
    AgentContext,
    AgentResult,
    HermesBase,
    HermesRunResult,
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
