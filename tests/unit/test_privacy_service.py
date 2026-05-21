"""
tests/unit/test_privacy_service.py — PrivacyService 单元测试

策略：mock session_factory / Redis / InfluxDB / QMD，
测试导出和删除的业务逻辑，不依赖外部存储。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rhythmind.privacy.service import (
    DeletionReport,
    PrivacyService,
    UserDataExport,
    _scan_user_keys,
)


class TestUserDataExport:

    def test_to_dict(self):
        export = UserDataExport(
            user_id="alice",
            exported_at="2026-01-01T00:00:00+00:00",
            agent_memory=[{"id": 1}],
            health_facts=[{"id": 2}],
        )
        d = export.to_dict()
        assert d["user_id"] == "alice"
        assert d["schema_version"] == "1.0"
        assert len(d["agent_memory"]) == 1

    def test_default_notes(self):
        export = UserDataExport(user_id="bob", exported_at="2026-01-01")
        assert export.notes == []
        assert export.influx_points == 0


class TestDeletionReport:

    def test_is_clean_true(self):
        report = DeletionReport(
            user_id="alice", deleted_at="2026-01-01",
            successes=[("agent_memory", "deleted 5 rows")],
        )
        assert report.is_clean is True

    def test_is_clean_false(self):
        report = DeletionReport(
            user_id="alice", deleted_at="2026-01-01",
            failures=[("redis", "connection error")],
        )
        assert report.is_clean is False

    def test_to_dict(self):
        report = DeletionReport(
            user_id="alice", deleted_at="2026-01-01",
            successes=[("pg", "ok")],
            failures=[("redis", "err")],
        )
        d = report.to_dict()
        assert d["is_clean"] is False
        assert len(d["successes"]) == 1
        assert len(d["failures"]) == 1


class TestPrivacyServiceExport:

    @pytest.mark.asyncio
    async def test_export_collects_all_data(self, user_id):
        mock_sess = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_sess.execute.return_value = mock_result
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, ["loop:alice:123"])

        svc = PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )

        bundle = await svc.export_user_data(user_id)

        assert bundle.user_id == user_id
        assert isinstance(bundle.agent_memory, list)
        assert isinstance(bundle.health_facts, list)
        assert "loop:alice:123" in bundle.redis_keys

    @pytest.mark.asyncio
    async def test_export_redis_failure_graceful(self, user_id):
        mock_sess = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_sess.execute.return_value = mock_result
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.scan.side_effect = Exception("connection refused")

        svc = PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )

        bundle = await svc.export_user_data(user_id)
        assert any("redis" in n for n in bundle.notes)


class TestPrivacyServiceDelete:

    @pytest.mark.asyncio
    async def test_delete_wrong_confirm_token(self, user_id):
        svc = PrivacyService()
        with pytest.raises(ValueError, match="confirm_token"):
            await svc.delete_user_data(user_id, confirm_token="wrong")

    @pytest.mark.asyncio
    async def test_delete_success(self, user_id):
        mock_sess = AsyncMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_sess.execute.return_value = mock_result
        mock_sess.commit = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, [])
        mock_redis.delete = AsyncMock()

        svc = PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )

        report = await svc.delete_user_data(user_id, confirm_token=user_id)

        assert report.is_clean is True
        assert len(report.successes) >= 2  # agent_memory + health_fact
        assert len(report.failures) == 0

    @pytest.mark.asyncio
    async def test_delete_pg_failure_best_effort(self, user_id):
        mock_sess = AsyncMock()
        mock_sess.execute.side_effect = Exception("db error")
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, [])

        svc = PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )

        report = await svc.delete_user_data(user_id, confirm_token=user_id)
        assert len(report.failures) >= 2  # agent_memory + health_fact both fail


class TestScanUserKeys:

    @pytest.mark.asyncio
    async def test_scan_finds_matching_keys(self):
        redis_client = AsyncMock()
        redis_client.scan.side_effect = [
            (0, ["loop:alice:intent1"]),
            (0, ["rl:user:*:alice"]),
            (0, ["session:alice:s1"]),
        ]
        keys = await _scan_user_keys(redis_client, "alice")
        assert len(keys) == 3

    @pytest.mark.asyncio
    async def test_scan_empty(self):
        redis_client = AsyncMock()
        redis_client.scan.return_value = (0, [])
        keys = await _scan_user_keys(redis_client, "nobody")
        assert keys == []
