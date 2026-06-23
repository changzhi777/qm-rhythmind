"""
tests/unit/test_memory_manager.py — MemoryManager 增删改查测试

每个测试使用 conftest.py 的 reset_db fixture（in-memory SQLite）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rhythmind.core.memory import MemoryManager


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


# ── init_db 启动逻辑（line 78-92）────────────────────────────────────

class TestInitDb:
    """init_db: dev/test 建表 + prod 跳过。"""

    @pytest.mark.asyncio
    async def test_init_db_skips_in_prod_env(self, monkeypatch, caplog):
        """line 85-89: env=prod 时 logger.warning + return（不建表）。"""
        from rhythmind.core.memory import manager as mgr_mod

        monkeypatch.setattr(mgr_mod.settings, "env", "prod")

        with caplog.at_level("WARNING"):
            await mgr_mod.init_db()

        # 验证日志含 prod 跳过提示
        assert any("init_db() called in prod" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_init_db_creates_tables_in_dev_env(self, monkeypatch):
        """line 90-92: env=dev 时调 Base.metadata.create_all（mock engine）。"""
        from contextlib import asynccontextmanager
        from rhythmind.core.memory import manager as mgr_mod

        monkeypatch.setattr(mgr_mod.settings, "env", "dev")

        # mock 全局 _engine.begin() 上下文管理器
        mock_conn = AsyncMock()
        mock_conn.run_sync = AsyncMock()

        @asynccontextmanager
        async def fake_begin():
            yield mock_conn

        # mock _engine（不调真的 _engine fixture）
        fake_engine = MagicMock()
        fake_engine.begin = fake_begin
        monkeypatch.setattr(mgr_mod, "_engine", fake_engine)

        await mgr_mod.init_db()

        # 验证 run_sync 被调（create_all）
        mock_conn.run_sync.assert_awaited_once()


# ── purge_expired 完整实现（line 235-252）────────────────────────────────

class TestPurgeExpired:
    """MemoryManager.purge_expired: 删除 expires_at < now 的所有 memory。"""

    @pytest.mark.asyncio
    async def test_purge_expired_returns_count_of_deleted_rows(self, monkeypatch):
        """line 244-252: 完整执行 — delete + result.rowcount + logger + return count。"""
        from contextlib import asynccontextmanager
        from rhythmind.core.memory import manager as mgr_mod

        # mock AsyncSessionLocal + session.begin()（line 244 `session.begin()` async CM）
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session_cm():
            yield mock_session

        @asynccontextmanager
        async def fake_begin():
            yield None  # session.begin() 进入事务

        mock_session.begin = fake_begin

        # AsyncSessionLocal() 返 async CM
        monkeypatch.setattr(mgr_mod, "AsyncSessionLocal", lambda: fake_session_cm())

        # purge_expired 是 MemoryManager class 方法（line 237）
        mgr = MemoryManager(user_id="u1", agent="a1")
        count = await mgr.purge_expired()

        # 验证 rowcount 透传
        assert count == 5
        mock_session.execute.assert_awaited_once()
        # 验证调用了 delete（call_args 包含 delete statement）
        call_str = str(mock_session.execute.call_args).upper()
        assert "DELETE" in call_str or "AGENTMEMORY" in call_str


# ── _build_upsert 方言选择（line 99-102）────────────────────────────────

class TestBuildUpsert:
    """_build_upsert: SQLite vs PostgreSQL 方言选择。"""

    def test_build_upsert_sqlite_uses_sqlite_dialect(self):
        """line 100: is_sqlite=True 时返 sqlite.insert 函数。"""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from rhythmind.core.memory import manager as mgr_mod

        result = mgr_mod._build_upsert(is_sqlite=True)
        assert callable(result)
        assert result is sqlite_insert

    def test_build_upsert_postgres_uses_postgres_dialect(self):
        """line 102: is_sqlite=False 时返 postgresql.insert 函数。"""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from rhythmind.core.memory import manager as mgr_mod

        result = mgr_mod._build_upsert(is_sqlite=False)
        assert callable(result)
        assert result is pg_insert
