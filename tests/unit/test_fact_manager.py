"""
tests/unit/test_fact_manager.py — HealthFact 时序知识图谱测试

策略：SQLite in-memory（conftest.py 的 reset_db fixture 自动建表），
所有测试覆盖时序语义：写入/过期/查询/历史/便捷方法。
"""
from __future__ import annotations

import pytest

from rhythmind.core.memory import FactManager

# ── 1. 基础写入与当前查询 ─────────────────────────────────────────────────────

class TestWriteAndQueryCurrent:

    @pytest.mark.asyncio
    async def test_write_fact_creates_current_record(self, user_id):
        fm = FactManager(user_id=user_id)
        fact = await fm.write_fact("user_goal", "targets", {"goal": "减脂"})

        assert fact.id is not None
        assert fact.is_current is True
        assert fact.object_json == {"goal": "减脂"}
        assert fact.valid_until is None

    @pytest.mark.asyncio
    async def test_query_current_returns_latest(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.write_fact("user_goal", "targets", {"goal": "减脂"})

        results = await fm.query_current("user_goal")
        assert len(results) == 1
        assert results[0].object_json == {"goal": "减脂"}

    @pytest.mark.asyncio
    async def test_query_current_with_predicate_filter(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.write_fact("baseline", "heart_rate_avg", {"value": 72.0})
        await fm.write_fact("baseline", "sleep_hours", {"value": 7.5})

        hr_facts = await fm.query_current("baseline", "heart_rate_avg")
        assert len(hr_facts) == 1
        assert hr_facts[0].object_json["value"] == 72.0

        sleep_facts = await fm.query_current("baseline", "sleep_hours")
        assert len(sleep_facts) == 1

    @pytest.mark.asyncio
    async def test_query_current_empty_when_no_facts(self, user_id):
        fm = FactManager(user_id=user_id)
        results = await fm.query_current("nonexistent_subject")
        assert results == []

    @pytest.mark.asyncio
    async def test_source_and_confidence_stored(self, user_id):
        fm = FactManager(user_id=user_id)
        fact = await fm.write_fact(
            "user_goal", "targets", {"goal": "马拉松"},
            source="coach_agent", confidence=0.95
        )
        assert fact.source == "coach_agent"
        assert fact.confidence == pytest.approx(0.95)


# ── 2. 自动 Invalidate（覆写语义）────────────────────────────────────────────

class TestAutoInvalidateOnWrite:

    @pytest.mark.asyncio
    async def test_write_fact_invalidates_previous(self, user_id):
        """写入新目标时，旧目标应被自动 invalidate。"""
        fm = FactManager(user_id=user_id)
        await fm.write_fact("user_goal", "targets", {"goal": "减脂"})
        await fm.write_fact("user_goal", "targets", {"goal": "马拉松"})

        current = await fm.query_current("user_goal")
        assert len(current) == 1
        assert current[0].object_json == {"goal": "马拉松"}

    @pytest.mark.asyncio
    async def test_history_preserved_after_update(self, user_id):
        """旧记录不删除，历史完整保留。"""
        fm = FactManager(user_id=user_id)
        await fm.write_fact("user_goal", "targets", {"goal": "减脂"})
        await fm.write_fact("user_goal", "targets", {"goal": "马拉松"})
        await fm.write_fact("user_goal", "targets", {"goal": "体能"})

        history = await fm.query_history("user_goal")
        assert len(history) == 3  # 全部记录保留

        # 只有最新一条是 current
        current_count = sum(1 for f in history if f.is_current)
        assert current_count == 1

    @pytest.mark.asyncio
    async def test_multiple_predicates_independent(self, user_id):
        """不同 predicate 互相独立，不因一个的写入而 invalidate 另一个。"""
        fm = FactManager(user_id=user_id)
        await fm.write_fact("baseline", "heart_rate_avg", {"value": 72.0})
        await fm.write_fact("baseline", "sleep_hours", {"value": 7.5})
        # 更新心率基线，不影响睡眠基线
        await fm.write_fact("baseline", "heart_rate_avg", {"value": 68.0})

        hr_current = await fm.query_current("baseline", "heart_rate_avg")
        sleep_current = await fm.query_current("baseline", "sleep_hours")

        assert len(hr_current) == 1
        assert hr_current[0].object_json["value"] == 68.0
        assert len(sleep_current) == 1  # 睡眠基线未被 invalidate


# ── 3. 手动 Invalidate ────────────────────────────────────────────────────────

class TestManualInvalidate:

    @pytest.mark.asyncio
    async def test_invalidate_fact_by_id(self, user_id):
        fm = FactManager(user_id=user_id)
        fact = await fm.write_fact("injury", "restricts", {"area": "膝盖"})

        ok = await fm.invalidate_fact(fact.id)
        assert ok is True

        current = await fm.query_current("injury")
        assert len(current) == 0

    @pytest.mark.asyncio
    async def test_invalidate_already_expired_returns_false(self, user_id):
        fm = FactManager(user_id=user_id)
        fact = await fm.write_fact("injury", "restricts", {"area": "膝盖"})
        await fm.invalidate_fact(fact.id)

        # 二次 invalidate 应返回 False
        ok = await fm.invalidate_fact(fact.id)
        assert ok is False

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_returns_false(self, user_id):
        fm = FactManager(user_id=user_id)
        ok = await fm.invalidate_fact(99999)
        assert ok is False

    @pytest.mark.asyncio
    async def test_invalidate_by_subject(self, user_id):
        """批量过期同 subject 下所有记录。"""
        fm = FactManager(user_id=user_id)
        # 追加写入两个伤病（不 invalidate 对方）
        await fm.write_fact_additive("injury", "restricts", {"area": "膝盖"})
        await fm.write_fact_additive("injury", "restricts", {"area": "腰部"})

        count = await fm.invalidate_by_subject("injury", "restricts")
        assert count == 2

        current = await fm.query_current("injury")
        assert len(current) == 0

    @pytest.mark.asyncio
    async def test_invalidate_by_subject_without_predicate(self, user_id):
        """不指定 predicate → 过期该 subject 下所有 predicate 的记录。"""
        fm = FactManager(user_id=user_id)
        await fm.write_fact("baseline", "heart_rate_avg", {"value": 72.0})
        await fm.write_fact("baseline", "sleep_hours", {"value": 7.5})

        count = await fm.invalidate_by_subject("baseline")
        assert count == 2

        hr = await fm.query_current("baseline", "heart_rate_avg")
        assert len(hr) == 0


# ── 4. 追加写入（Additive）────────────────────────────────────────────────────

class TestAdditiveWrite:

    @pytest.mark.asyncio
    async def test_additive_does_not_invalidate_siblings(self, user_id):
        """write_fact_additive 不影响已有的并行有效记录。"""
        fm = FactManager(user_id=user_id)
        await fm.write_fact_additive("injury", "restricts", {"area": "膝盖"})
        await fm.write_fact_additive("injury", "restricts", {"area": "腰部"})

        current = await fm.query_current("injury", "restricts")
        assert len(current) == 2

    @pytest.mark.asyncio
    async def test_additive_vs_overwrite(self, user_id):
        """write_fact 覆写 vs write_fact_additive 追加的行为对比。"""
        fm = FactManager(user_id=user_id)
        # 追加两条
        await fm.write_fact_additive("tag", "has", {"v": "A"})
        await fm.write_fact_additive("tag", "has", {"v": "B"})
        # 覆写（invalidate 前两条，只留C）
        await fm.write_fact("tag", "has", {"v": "C"})

        current = await fm.query_current("tag", "has")
        assert len(current) == 1
        assert current[0].object_json["v"] == "C"


# ── 5. 历史查询 ───────────────────────────────────────────────────────────────

class TestHistoryQuery:

    @pytest.mark.asyncio
    async def test_query_history_includes_expired(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.write_fact("user_goal", "targets", {"goal": "减脂"})   # 会被 invalidate  # noqa: E501
        await fm.write_fact("user_goal", "targets", {"goal": "增肌"})   # 会被 invalidate  # noqa: E501
        await fm.write_fact("user_goal", "targets", {"goal": "马拉松"}) # 当前有效

        history = await fm.query_history("user_goal")
        assert len(history) == 3
        # 按 valid_from 倒序：最新在前
        assert history[0].object_json["goal"] == "马拉松"

    @pytest.mark.asyncio
    async def test_query_history_limit(self, user_id):
        fm = FactManager(user_id=user_id)
        for i in range(5):
            await fm.write_fact("baseline", "steps", {"value": 8000 + i * 100})

        limited = await fm.query_history("baseline", "steps", limit=3)
        assert len(limited) == 3


# ── 6. 用户隔离 ───────────────────────────────────────────────────────────────

class TestUserIsolation:

    @pytest.mark.asyncio
    async def test_facts_isolated_by_user(self, user_id):
        fm1 = FactManager(user_id=user_id)
        fm2 = FactManager(user_id="other_user_999")

        await fm1.write_fact("user_goal", "targets", {"goal": "减脂"})
        await fm2.write_fact("user_goal", "targets", {"goal": "增肌"})

        # 各自只能看到自己的
        u1_facts = await fm1.query_current("user_goal")
        u2_facts = await fm2.query_current("user_goal")

        assert len(u1_facts) == 1
        assert u1_facts[0].object_json["goal"] == "减脂"
        assert len(u2_facts) == 1
        assert u2_facts[0].object_json["goal"] == "增肌"


# ── 7. 便捷方法 ───────────────────────────────────────────────────────────────

class TestConvenienceMethods:

    @pytest.mark.asyncio
    async def test_set_goal_and_get_current_goal(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.set_goal("减脂", {"target_body_fat": 0.18})

        goal = await fm.get_current_goal()
        assert goal is not None
        assert goal["goal"] == "减脂"
        assert goal["target_body_fat"] == 0.18

    @pytest.mark.asyncio
    async def test_set_goal_replaces_previous(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.set_goal("减脂")
        await fm.set_goal("马拉松", {"deadline": "2027-03"})

        goal = await fm.get_current_goal()
        assert goal["goal"] == "马拉松"

    @pytest.mark.asyncio
    async def test_add_injury_and_query(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.add_injury("膝盖", "避免深蹲")

        injuries = await fm.get_current_injuries()
        assert len(injuries) == 1
        assert injuries[0]["area"] == "膝盖"

    @pytest.mark.asyncio
    async def test_recover_from_specific_injury(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.add_injury("膝盖", "避免深蹲")
        await fm.add_injury("腰部", "避免硬拉")

        count = await fm.recover_from_injury("膝盖")
        assert count == 1

        injuries = await fm.get_current_injuries()
        assert len(injuries) == 1
        assert injuries[0]["area"] == "腰部"

    @pytest.mark.asyncio
    async def test_recover_all_injuries(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.add_injury("膝盖", "避免深蹲")
        await fm.add_injury("腰部", "避免硬拉")

        count = await fm.recover_from_injury()  # 全部康复
        assert count == 2
        assert await fm.get_current_injuries() == []

    @pytest.mark.asyncio
    async def test_get_all_current(self, user_id):
        fm = FactManager(user_id=user_id)
        await fm.set_goal("马拉松")
        await fm.write_fact("baseline", "heart_rate_avg", {"value": 72.0})
        await fm.add_injury("膝盖", "避免深蹲")

        all_facts = await fm.get_all_current()
        subjects = {f.subject for f in all_facts}
        assert "user_goal" in subjects
        assert "baseline" in subjects
        assert "injury" in subjects
