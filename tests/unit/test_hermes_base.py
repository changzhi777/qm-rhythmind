"""
tests/unit/test_hermes_base.py — HermesBase 闭环流程测试

通过 Mock 替换 LLM 调用和 QMD，专注测试五步闭环的控制流。
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rhythmind.core.hermes_base import AgentContext, AgentResult, HermesBase, HermesRunResult
from rhythmind.core.memory import MemoryRecallResult
from rhythmind.core.compliance.gate import ComplianceLevel


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
        skill_ctx: list[dict[str, Any]],
    ) -> AgentResult:
        return AgentResult(
            output=f"echo: {ctx.input_data.get('text', '')}",
            confidence=self._confidence,
            skill_candidates=["echo_template"],
            memory_updates={"last_echo": ctx.input_data.get("text", "")},
        )


class TestHermesBaseLoop:

    @pytest.mark.asyncio
    @patch("rhythmind.core.qmd.client.QMDClient.query", new_callable=AsyncMock)
    @patch("rhythmind.core.skill.engine.SkillEngine.persist_to_qmd", new_callable=AsyncMock)
    async def test_pass_flow_completes(
        self, mock_persist, mock_qmd_query, user_id: str, session_id: str
    ):
        """PASS 流程：execute → compliance PASS → memory 更新 → skill 提取"""
        mock_qmd_query.return_value = []
        mock_persist.return_value = None

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
    @patch("rhythmind.core.qmd.client.QMDClient.query", new_callable=AsyncMock)
    async def test_block_flow_skips_memory(
        self, mock_qmd_query, user_id: str, session_id: str
    ):
        """BLOCK 流程：memory 和 skill 不应被更新"""
        mock_qmd_query.return_value = []

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
    @patch("rhythmind.core.qmd.client.QMDClient.query", new_callable=AsyncMock)
    @patch("rhythmind.core.skill.engine.SkillEngine.persist_to_qmd", new_callable=AsyncMock)
    async def test_warn_appends_disclaimer(
        self, mock_persist, mock_qmd_query, user_id: str, session_id: str
    ):
        """WARN 流程：输出包含免责声明"""
        mock_qmd_query.return_value = []
        mock_persist.return_value = None

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
    @patch("rhythmind.core.qmd.client.QMDClient.query")
    @patch("rhythmind.core.skill.engine.SkillEngine.persist_to_qmd", new_callable=AsyncMock)
    async def test_qmd_unavailable_graceful_degradation(
        self, mock_persist, mock_qmd_query, user_id: str, session_id: str
    ):
        """QMD 不可用时降级处理，不中断主流程"""
        from rhythmind.core.qmd.client import QMDUnavailableError
        mock_qmd_query.side_effect = QMDUnavailableError("QMD down")
        mock_persist.return_value = None

        agent = EchoAgent(user_id=user_id, confidence=0.90)
        ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="test",
            input_data={"text": "test"},
        )
        # 不应抛出异常
        result = await agent.run(ctx)
        assert result.success is True  # 降级为空 skill_ctx，继续执行
