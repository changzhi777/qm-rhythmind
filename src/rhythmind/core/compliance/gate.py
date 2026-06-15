# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/compliance/gate.py — 三级合规门控

输出分级：
  PASS  — confidence >= pass_threshold，无命中关键词
  WARN  — confidence >= warn_threshold 且 < pass_threshold，
          或命中 warn_keywords → 追加免责声明
  BLOCK — confidence < warn_threshold，或命中 block_keywords
          → requires_human_review=True，输出置空

调用位置：HermesBase.run() 中 execute() 之后、memory.update() 之前。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rhythmind.config import settings

from .keywords import KeywordRules, load_keyword_rules

logger = logging.getLogger(__name__)


class ComplianceLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass
class ComplianceResult:
    level: ComplianceLevel
    output: Any                          # BLOCK 时为 None
    confidence: float
    skill_candidates: list[str] = field(default_factory=list)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    # P3 解耦：拆分 requires_human_review 为两个独立信号
    #   compliance_block — 合规门禁拦截（高风险，建议拒绝）
    #   advisor_review   — Agent/Advisor 主动建议复核（中等风险）
    compliance_block: bool = False
    advisor_review: bool = False
    triggered_keywords: list[str] = field(default_factory=list)
    disclaimer_appended: bool = False

    @property
    def requires_human_review(self) -> bool:
        """向后兼容属性：任一信号触发即 True。下游消费者可继续使用此字段。

        新代码应直接消费 compliance_block / advisor_review 以区分根因。
        """
        return self.compliance_block or self.advisor_review


class ComplianceGate:
    """
    无状态合规检查器，可在多 Agent 间共享。

    validate() 接收 AgentResult（鸭子类型：有 output/confidence/
    skill_candidates/memory_updates 属性），返回 ComplianceResult。
    """

    def __init__(self, rules: KeywordRules | None = None) -> None:
        self._rules: KeywordRules = rules or load_keyword_rules()
        self._pass_threshold = settings.compliance_pass_threshold
        self._warn_threshold = settings.compliance_warn_threshold

    def validate(
        self,
        result: Any,              # AgentResult（避免循环导入）
        confidence_override: float | None = None,
    ) -> ComplianceResult:
        """
        主入口：合规校验。

        Args:
            result:               AgentResult 实例
            confidence_override:  可覆盖 result.confidence（测试用）
        """
        confidence = confidence_override if confidence_override is not None else result.confidence
        output_text = self._extract_text(result.output)

        # 1. 关键词扫描
        blocked_kws = self._scan(output_text, self._rules.block_patterns)
        warned_kws = self._scan(output_text, self._rules.warn_patterns)

        # 2. 分级决策
        if blocked_kws or confidence < self._warn_threshold:
            level = ComplianceLevel.BLOCK
            logger.warning(
                "compliance.BLOCK confidence=%.2f blocked_kws=%s",
                confidence, blocked_kws,
            )
            try:
                from rhythmind.observability import COMPLIANCE_BLOCKS
                COMPLIANCE_BLOCKS.labels("output_gate").inc()
            except Exception:
                pass
            return ComplianceResult(
                level=level,
                output=None,
                confidence=confidence,
                compliance_block=True,
                triggered_keywords=blocked_kws,
            )

        final_output = result.output
        disclaimer_appended = False

        if warned_kws or confidence < self._pass_threshold:
            level = ComplianceLevel.WARN
            # 追加免责声明到文本型输出
            if isinstance(final_output, str) and self._rules.disclaimer_zh:
                final_output = f"{final_output}\n\n{self._rules.disclaimer_zh}"
                disclaimer_appended = True
            elif isinstance(final_output, dict) and "text" in final_output:
                final_output = dict(final_output)
                final_output["text"] = (
                    f"{final_output['text']}\n\n{self._rules.disclaimer_zh}"
                )
                disclaimer_appended = True
            logger.info(
                "compliance.WARN confidence=%.2f warned_kws=%s", confidence, warned_kws
            )
        else:
            level = ComplianceLevel.PASS
            logger.debug("compliance.PASS confidence=%.2f", confidence)

        return ComplianceResult(
            level=level,
            output=final_output,
            confidence=confidence,
            skill_candidates=list(result.skill_candidates),
            memory_updates=dict(result.memory_updates),
            triggered_keywords=warned_kws,
            disclaimer_appended=disclaimer_appended,
        )

    def pre_check(self, raw_input: dict[str, Any]) -> bool:
        """
        请求进入前的前置合规检查（在 HealthRouter 层调用）。

        目前检查：input text 是否包含 block_keywords。
        Returns:
            True 表示放行，False 表示拦截。
        """
        text = " ".join(str(v) for v in raw_input.values() if isinstance(v, str))
        blocked = self._scan(text, self._rules.block_patterns)
        if blocked:
            logger.warning("compliance.pre_check BLOCKED kws=%s", blocked)
            try:
                from rhythmind.observability import COMPLIANCE_BLOCKS
                COMPLIANCE_BLOCKS.labels("prompt_audit").inc()
            except Exception:
                pass
            return False
        return True

    # ── 内部工具 ──────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(output: Any) -> str:
        if isinstance(output, str):
            return output
        if isinstance(output, dict):
            # 支持 {"text": "...", ...} 或 {"content": "..."}
            return str(output.get("text") or output.get("content") or output)
        return str(output)

    @staticmethod
    def _scan(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
        hits = []
        for pat in patterns:
            m = pat.search(text)
            if m:
                hits.append(m.group(0))
        return hits
