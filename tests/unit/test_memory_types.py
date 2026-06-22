# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_memory_types.py — MemoryType / MemoryEntry / MemoryRecallResult

覆盖 line 51-53 (build_namespace 内嵌 safe 函数) + line 69 (to_dict)。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from rhythmind.core.memory.types import (
    MemoryEntry,
    MemoryRecallResult,
    MemoryType,
)


class TestBuildNamespace:
    """MemoryEntry.build_namespace 字符清理 + 4 段格式。"""

    def test_normal_ids_format_correctly(self):
        """普通 ID（字母数字 + 下划线）应原样保留，4 段格式 user.{user_id}.{agent}.{key}。"""
        ns = MemoryEntry.build_namespace("alice", "coach_agent", "favorite_sport")
        assert ns == "user.alice.coach_agent.favorite_sport"

    def test_special_chars_replaced_with_underscore(self):
        """特殊字符（空格/点/斜杠/中文）应替换为下划线（line 51-52）。"""
        # "alice@2024" → "alice_2024"（@ 不是 [a-z0-9_-] → _）
        ns = MemoryEntry.build_namespace("alice@2024", "agent", "key")
        assert ns == "user.alice_2024.agent.key"

    def test_uppercase_converted_to_lowercase(self):
        """大写字母应转小写（line 52 `.lower()`）。"""
        ns = MemoryEntry.build_namespace("ALICE", "CoachAgent", "Key")
        assert ns == "user.alice.coachagent.key"

    def test_mixed_special_and_unicode(self):
        """混合特殊字符 + Unicode（中文）应被替换。"""
        ns = MemoryEntry.build_namespace("用户@1", "agent-X", "key.path")
        # 验证：每段只含 [a-z0-9_-]
        for segment in ns.split("."):
            for ch in segment:
                assert ch.isalnum() or ch in "-_"

    def test_empty_or_pure_special_handled(self):
        """纯特殊字符输入不应崩溃（被全部替换为下划线并 join 合并）。"""
        ns = MemoryEntry.build_namespace("@@@", "###", "!!!")
        # 每段都被替换：连续 _ 会被 "_".join 合并为单 _
        for segment in ns.split("."):
            # 非空 + 只含合法字符
            assert segment != ""
            for ch in segment:
                assert ch.isalnum() or ch == "_"
        # 4 段格式保留
        assert len(ns.split(".")) == 4
        # 首段固定 "user"
        assert ns.split(".")[0] == "user"


class TestToDict:
    """MemoryRecallResult.to_dict: entry 列表 → key→value 映射（line 69）。"""

    def test_to_dict_maps_keys_to_values(self):
        """to_dict 应返回 {entry.key: entry.value} 映射。"""
        result = MemoryRecallResult(entries=[
            MemoryEntry(
                namespace="u.a.coach.sport",
                key="sport",
                value="running",
                mem_type=MemoryType.USER,
            ),
            MemoryEntry(
                namespace="u.a.coach.goal",
                key="goal",
                value="marathon",
                mem_type=MemoryType.PROJECT,
            ),
        ])
        d = result.to_dict()
        assert d == {"sport": "running", "goal": "marathon"}

    def test_to_dict_empty_returns_empty_dict(self):
        """空 entries 列表 to_dict 返 {}。"""
        result = MemoryRecallResult()
        assert result.to_dict() == {}

    def test_to_dict_duplicate_keys_last_one_wins(self):
        """重复 key 时后者覆盖前者（dict 构造行为）。"""
        result = MemoryRecallResult(entries=[
            MemoryEntry(namespace="u1", key="x", value="first", mem_type=MemoryType.USER),
            MemoryEntry(namespace="u1", key="x", value="second", mem_type=MemoryType.USER),
        ])
        d = result.to_dict()
        # Python dict 构造后者覆盖
        assert d == {"x": "second"}
