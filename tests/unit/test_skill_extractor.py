# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_skill_extractor.py — SkillExtractor 单元测试

覆盖场景：
  - extract(): 低 confidence 跳过 / 高 confidence 无 candidates / 高 confidence 提取 candidates
  - _format_skill(): 模板含 candidate/task_type/agent 字段
  - _skill_id(): 稳定 hash + agent 名前缀
"""
from __future__ import annotations

import hashlib

from rhythmind.core.skill.extractor import SkillExtractor


class TestExtract:
    def test_skips_when_confidence_below_threshold(self):
        """confidence < 0.85 时应返回空列表，不调用 _format_skill。"""
        extractor = SkillExtractor()
        result = extractor.extract(
            task_type="analyze_metrics",
            skill_candidates=["should_be_ignored"],
            output={"x": 1},
            confidence=0.50,  # 低于 0.85 阈值
            agent="metrics_agent",
        )
        assert result == []

    def test_returns_empty_when_no_candidates(self):
        """高 confidence 但 skill_candidates 为空时，返回空列表。"""
        extractor = SkillExtractor()
        result = extractor.extract(
            task_type="analyze_metrics",
            skill_candidates=[],
            output={"x": 1},
            confidence=0.95,
            agent="metrics_agent",
        )
        assert result == []

    def test_extracts_each_candidate_at_high_confidence(self):
        """高 confidence + 有 candidates 时，每个 candidate 生成一条 skill。"""
        extractor = SkillExtractor()
        result = extractor.extract(
            task_type="analyze_metrics",
            skill_candidates=["handle_high_hrv", "detect_anomaly"],
            output={"x": 1},
            confidence=0.90,
            agent="data_agent",
        )
        assert len(result) == 2
        # 每条都有 id/content/agent/task_type
        for skill in result:
            assert set(skill.keys()) == {"id", "content", "agent", "task_type"}
            assert skill["agent"] == "data_agent"
            assert skill["task_type"] == "analyze_metrics"
        # candidate 名称进入 content
        assert "handle_high_hrv" in result[0]["content"]
        assert "detect_anomaly" in result[1]["content"]

    def test_id_includes_agent_prefix_and_is_stable(self):
        """id 应含 agent 名前缀，同一输入产生稳定 hash。"""
        extractor = SkillExtractor()
        result = extractor.extract(
            task_type="t1",
            skill_candidates=["c1"],
            output=None,
            confidence=0.95,
            agent="coach_agent",
        )
        skill_id = result[0]["id"]
        assert skill_id.startswith("skill_coach_agent_")
        # 同一输入再次调用应得相同 id
        result2 = extractor.extract(
            task_type="t1",
            skill_candidates=["c1"],
            output=None,
            confidence=0.95,
            agent="coach_agent",
        )
        assert result2[0]["id"] == skill_id

    def test_different_agents_produce_different_ids(self):
        """不同 agent 对同一 candidate 应产生不同 id。"""
        extractor = SkillExtractor()
        r1 = extractor.extract("t1", ["c1"], None, 0.95, "agent_a")
        r2 = extractor.extract("t1", ["c1"], None, 0.95, "agent_b")
        assert r1[0]["id"] != r2[0]["id"]


class TestFormatSkill:
    def test_format_skill_template_contains_key_fields(self):
        """_format_skill 模板应含 candidate/task_type/agent 三个字段。"""
        formatted = SkillExtractor._format_skill(
            candidate="my_skill",
            task_type="analyze_metrics",
            agent="data_agent",
        )
        assert "## my_skill" in formatted
        assert "**Agent**: data_agent" in formatted
        assert "task_type = analyze_metrics" in formatted
        assert "自动提取自高置信度执行结果" in formatted


class TestSkillId:
    def test_skill_id_uses_sha256_first_16_hex(self):
        """_skill_id 应使用 SHA256 前 16 个 hex 字符作为 hash。"""
        agent = "test_agent"
        content = "## skill\n**Agent**: test_agent"
        expected_hash = hashlib.sha256(f"{agent}:{content}".encode()).hexdigest()[:16]
        assert SkillExtractor._skill_id(agent, content) == f"skill_{agent}_{expected_hash}"

    def test_skill_id_changes_with_content(self):
        """不同 content 产生不同 id。"""
        id1 = SkillExtractor._skill_id("a", "content1")
        id2 = SkillExtractor._skill_id("a", "content2")
        assert id1 != id2
