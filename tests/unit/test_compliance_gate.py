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
