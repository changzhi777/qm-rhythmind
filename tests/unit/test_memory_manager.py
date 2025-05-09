"""
tests/unit/test_memory_manager.py — MemoryManager 增删改查测试

每个测试使用 conftest.py 的 reset_db fixture（in-memory SQLite）。
"""
from __future__ import annotations

import pytest

from rhythmind.core.memory import MemoryManager, MemoryType


class TestMemoryManager:

    @pytest.mark.asyncio
    async def test_write_and_recall(self, user_id: str):
        """写入后能正确召回。"""
        mgr = MemoryManager(user_id=user_id, agent="data_agent")
        await mgr.write("metrics_baseline", {"hr": 72, "steps": 8000})

        result = await mgr.recall("upload_data")
        assert result.total == 1
        val = result.get("metrics_baseline")
        assert val["hr"] == 72

    @pytest.mark.asyncio
    async def test_upsert_updates_value(self, user_id: str):
        """同 key 多次写入，保留最新值。"""
        mgr = MemoryManager(user_id=user_id, agent="data_agent")
        await mgr.write("sport_type", "running")
        await mgr.write("sport_type", "cycling")

        result = await mgr.recall("sport")
        assert result.get("sport_type") == "cycling"
        assert result.total == 1  # 不重复插入

    @pytest.mark.asyncio
    async def test_namespace_isolation(self, user_id: str):
        """不同 user 的记忆互不可见。"""
        mgr_a = MemoryManager(user_id="user_a", agent="data_agent")
        mgr_b = MemoryManager(user_id="user_b", agent="data_agent")

        await mgr_a.write("secret", "user_a_data")
        result_b = await mgr_b.recall("secret")

        assert result_b.total == 0
        assert result_b.get("secret") is None

    @pytest.mark.asyncio
    async def test_agent_isolation(self, user_id: str):
        """同 user 不同 agent 的记忆互不可见。"""
        mgr_data = MemoryManager(user_id=user_id, agent="data_agent")
        mgr_coach = MemoryManager(user_id=user_id, agent="coach_agent")

        await mgr_data.write("my_key", "from_data")
        result = await mgr_coach.recall("my_key")

        assert result.get("my_key") is None

    @pytest.mark.asyncio
    async def test_batch_update(self, user_id: str):
        """batch update() 正确写入多个 key。"""
        mgr = MemoryManager(user_id=user_id, agent="data_agent")
        updates = {
            "metrics_baseline": {"hr": 65},
            "last_report_date": "2026-05-08",
            "improvement_list": ["增加步数", "改善睡眠"],
        }
        await mgr.update(updates)

        result = await mgr.recall("report")
        assert result.get("last_report_date") == "2026-05-08"
        assert result.get("improvement_list") == ["增加步数", "改善睡眠"]

    @pytest.mark.asyncio
    async def test_soft_delete(self, user_id: str):
        """软删除后不再召回。"""
        mgr = MemoryManager(user_id=user_id, agent="data_agent")
        await mgr.write("to_delete", "value")
        await mgr.delete("to_delete")

        result = await mgr.recall("delete")
        assert result.get("to_delete") is None

    @pytest.mark.asyncio
    async def test_namespace_safe_chars(self):
        """特殊字符的 user_id 不破坏 namespace 构建。"""
        mgr = MemoryManager(user_id="user@domain.com", agent="data-agent")
        await mgr.write("key", "value")
        result = await mgr.recall("key")
        assert result.get("key") == "value"
