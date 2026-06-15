"""
tests/unit/test_compliance_gate.py — ComplianceGate 三级分级测试
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rhythmind.core.compliance.gate import ComplianceGate, ComplianceLevel
from rhythmind.core.compliance.keywords import KeywordRules

# ── 测试用 AgentResult stub ───────────────────────────────────────────────

@dataclass
class FakeAgentResult:
    output: Any
    confidence: float
    skill_candidates: list[str] = field(default_factory=list)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = False


# ── 测试用规则（不依赖文件系统）─────────────────────────────────────────

def _make_gate() -> ComplianceGate:
    rules = KeywordRules(
        block_patterns=[re.compile(r"确诊"), re.compile(r"处方")],
        warn_patterns=[re.compile(r"治疗"), re.compile(r"康复训练")],
        disclaimer_zh="⚠️ 仅供参考，不构成医疗建议。",
    )
    gate = ComplianceGate(rules=rules)
    return gate


class TestComplianceGate:

    def test_pass_clean_output(self):
        """正常输出，高置信度 → PASS"""
        gate = _make_gate()
        result = FakeAgentResult(output="今日跑步 5 公里，表现优秀！", confidence=0.92)
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.PASS
        assert checked.output == result.output
        assert not checked.requires_human_review

    def test_warn_low_confidence(self):
        """置信度 [0.50, 0.75) → WARN + disclaimer"""
        gate = _make_gate()
        result = FakeAgentResult(output="建议增加有氧训练。", confidence=0.65)
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.WARN
        assert "⚠️" in checked.output
        assert checked.disclaimer_appended

    def test_warn_keyword_hit(self):
        """命中 warn_keywords → WARN + disclaimer"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="可以进行康复训练以恢复体能。", confidence=0.90
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.WARN
        assert "康复训练" in checked.triggered_keywords
        assert "⚠️" in checked.output

    def test_block_keyword_hit(self):
        """命中 block_keywords → BLOCK，output=None"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="您已确诊为2型糖尿病。", confidence=0.95
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.BLOCK
        assert checked.output is None
        assert checked.requires_human_review
        assert "确诊" in checked.triggered_keywords

    def test_block_very_low_confidence(self):
        """置信度 < 0.50 → BLOCK"""
        gate = _make_gate()
        result = FakeAgentResult(output="建议减少运动。", confidence=0.45)
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.BLOCK
        assert checked.requires_human_review

    def test_block_has_no_skill_candidates(self):
        """BLOCK 结果不应携带 skill_candidates（避免错误沉淀）"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="处方建议服药。", confidence=0.90,
            skill_candidates=["bad_skill"]
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.BLOCK
        assert checked.skill_candidates == []

    def test_dict_output_disclaimer_injection(self):
        """dict 型 output 的 text 字段追加免责声明"""
        gate = _make_gate()
        result = FakeAgentResult(
            output={"text": "建议治疗后再运动。", "score": 0.8},
            confidence=0.90,
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.WARN
        assert "⚠️" in checked.output["text"]

    def test_pre_check_blocks_malicious_input(self):
        """pre_check 拦截含 block_keywords 的输入"""
        gate = _make_gate()
        bad_input = {"text": "我需要一个治疗处方"}
        assert gate.pre_check(bad_input) is False

    def test_pre_check_allows_normal_input(self):
        """pre_check 放行正常输入"""
        gate = _make_gate()
        good_input = {"text": "我今天跑步了 5 公里"}
        assert gate.pre_check(good_input) is True


# ── P3 解耦回归：compliance_block / advisor_review / requires_human_review 派生 ──


class TestComplianceResultDecoupling:
    """P3 修复回归：ComplianceResult.requires_human_review 改为 @property 派生，
    下游可通过 compliance_block / advisor_review 区分根因。
    """

    def test_property_derives_from_either_signal(self):
        """requires_human_review = compliance_block OR advisor_review。"""
        from rhythmind.core.compliance.gate import ComplianceResult

        cr1 = ComplianceResult(
            level=ComplianceLevel.PASS, output="x", confidence=0.9,
            compliance_block=True,
        )
        assert cr1.requires_human_review is True
        assert cr1.compliance_block is True
        assert cr1.advisor_review is False

        cr2 = ComplianceResult(
            level=ComplianceLevel.PASS, output="x", confidence=0.9,
            advisor_review=True,
        )
        assert cr2.requires_human_review is True
        assert cr2.compliance_block is False
        assert cr2.advisor_review is True

        cr3 = ComplianceResult(
            level=ComplianceLevel.PASS, output="x", confidence=0.9,
        )
        assert cr3.requires_human_review is False

    def test_construction_rejects_old_field_name(self):
        """requires_human_review 不再是构造参数，TypeError 强制使用新字段。"""
        import pytest as _pt

        from rhythmind.core.compliance.gate import ComplianceResult

        with _pt.raises(TypeError, match="requires_human_review"):
            ComplianceResult(
                level=ComplianceLevel.PASS, output="x", confidence=0.9,
                requires_human_review=True,  # type: ignore[call-arg]
            )

    def test_block_path_sets_compliance_block(self):
        """BLOCK 分支：validate() 返回的 ComplianceResult.compliance_block=True。"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="处方建议服药。", confidence=0.90,
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.BLOCK
        assert checked.compliance_block is True
        assert checked.advisor_review is False
        # 向后兼容：property 仍返回 True
        assert checked.requires_human_review is True

    def test_warn_path_keeps_both_signals_false(self):
        """WARN 分支：两个新信号都 False，property 也 False。"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="建议治疗后再运动。", confidence=0.90,
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.WARN
        assert checked.compliance_block is False
        assert checked.advisor_review is False
        assert checked.requires_human_review is False

    def test_pass_path_keeps_both_signals_false(self):
        """PASS 分支：两个新信号都 False，property 也 False。"""
        gate = _make_gate()
        result = FakeAgentResult(
            output="您今天跑步 5 公里，状态不错。", confidence=0.95,
        )
        checked = gate.validate(result)
        assert checked.level == ComplianceLevel.PASS
        assert checked.compliance_block is False
        assert checked.advisor_review is False
        assert checked.requires_human_review is False
