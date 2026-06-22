"""
tests/unit/test_privacy_service.py — PrivacyService 单元测试

策略：mock session_factory / Redis / InfluxDB / QMD，
测试导出和删除的业务逻辑，不依赖外部存储。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


# ── Influx + QMD 子系统辅助方法（line 172-174/245-265/289-326）────────

class TestPrivacyServiceInfluxQmd:
    """覆盖 _count_influx_points / _delete_influx_points / _purge_qmd_namespaces
    + export/delete 主流程对这些子系统的成功失败处理。"""

    @pytest.mark.asyncio
    async def test_count_influx_points_returns_zero_when_token_unset(self, monkeypatch):
        """influxdb_token 未配置时 _count_influx_points 直接返 0（line 289-291）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "")

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        count = await svc._count_influx_points("alice")
        assert count == 0

    @pytest.mark.asyncio
    async def test_count_influx_points_sums_query_range_values(self, monkeypatch):
        """_count_influx_points 累加 query_range 各 series 的 values 数（line 292-303）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        # mock influx client（line 297 延迟创建）
        mock_series = MagicMock()
        mock_series.values = [1, 2, 3]  # 3 points
        mock_series2 = MagicMock()
        mock_series2.values = [10, 20]  # 2 points
        mock_influx = MagicMock()
        mock_influx.query_range = AsyncMock(return_value={
            "heart_rate_avg": mock_series,
            "steps": mock_series2,
        })

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        svc._influx = mock_influx

        count = await svc._count_influx_points("alice")
        assert count == 5  # 3 + 2

    @pytest.mark.asyncio
    async def test_count_influx_points_returns_zero_on_query_error(self, monkeypatch):
        """query_range 抛错时 _count_influx_points 兜底返 0（line 304-305）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        mock_influx = MagicMock()
        mock_influx.query_range = AsyncMock(side_effect=Exception("connection refused"))

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        svc._influx = mock_influx

        count = await svc._count_influx_points("alice")
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_influx_points_returns_false_when_token_unset(self, monkeypatch):
        """influxdb_token 未配置时 _delete_influx_points 返 False（line 311-313）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "")

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        ok = await svc._delete_influx_points("alice")
        assert ok is False

    @pytest.mark.asyncio
    async def test_delete_influx_points_returns_false_on_not_implemented(self, monkeypatch):
        """delete_user_data 抛 NotImplementedError 时返 False（line 316-319）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        mock_influx = MagicMock()
        mock_influx.delete_user_data = AsyncMock(
            side_effect=NotImplementedError("not supported")
        )

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        svc._influx = mock_influx

        ok = await svc._delete_influx_points("alice")
        assert ok is False

    @pytest.mark.asyncio
    async def test_purge_qmd_namespaces_raises_when_purge_user_missing(self, monkeypatch):
        """QMDClient 无 purge_user 方法时抛 NotImplementedError（line 326）。"""
        from rhythmind.privacy import service as svc_mod

        mock_qmd = MagicMock(spec=[])  # spec=[] 表示无任何属性
        # QMDClient 实例

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        svc._qmd = mock_qmd

        with pytest.raises(NotImplementedError, match="QMDClient.purge_user"):
            await svc._purge_qmd_namespaces("alice")

    @pytest.mark.asyncio
    async def test_purge_qmd_namespaces_calls_purge_user(self):
        """_purge_qmd_namespaces 正常路径：调用 qmd.purge_user(user_id)。"""
        from rhythmind.privacy import service as svc_mod

        mock_qmd = MagicMock()
        mock_qmd.purge_user = AsyncMock()

        svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
        svc._qmd = mock_qmd

        await svc._purge_qmd_namespaces("alice")
        mock_qmd.purge_user.assert_awaited_once_with("alice")

    @pytest.mark.asyncio
    async def test_export_influx_failure_records_note(self, monkeypatch):
        """export_user_data: _count_influx_points 抛错时记 notes（line 172-174），不阻断。"""
        from rhythmind.privacy import service as svc_mod

        # 让 _count_influx_points 走抛错路径
        async def raise_error(uid):
            raise Exception("simulated influx failure")

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)
        mock_sess.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        svc = svc_mod.PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=AsyncMock(),
        )
        svc._count_influx_points = raise_error  # type: ignore[method-assign]

        bundle = await svc.export_user_data("alice")
        # influxdb 失败应被记到 notes，不抛
        assert any("influxdb" in n and "skipped" in n for n in bundle.notes)

    @pytest.mark.asyncio
    async def test_delete_influx_success_records_success(self, monkeypatch):
        """delete_user_data: influx 成功时记 successes（line 255-256）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)
        mock_sess.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, [])

        svc = svc_mod.PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )
        # mock _delete_influx_points 直接返 True（line 255-256 路径）
        svc._delete_influx_points = AsyncMock(return_value=True)  # type: ignore[method-assign]

        report = await svc.delete_user_data("alice", confirm_token="alice")
        # influxdb 应在 successes 中
        assert any(name == "influxdb" for name, _ in report.successes)

    @pytest.mark.asyncio
    async def test_delete_redis_failure_recorded(self, monkeypatch):
        """delete_user_data: Redis 操作失败时记 failures（line 245-246）。"""
        from rhythmind.privacy import service as svc_mod

        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)
        mock_sess.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        # mock redis：scan 时抛错
        mock_redis = MagicMock()
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("redis down"))
        mock_redis.aclose = AsyncMock()

        svc = svc_mod.PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )
        # influx/qmd 成功（避免多系统失败掩盖 redis 失败）
        svc._delete_influx_points = AsyncMock(return_value=True)  # type: ignore[method-assign]
        svc._purge_qmd_namespaces = AsyncMock()  # type: ignore[method-assign]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            report = await svc.delete_user_data("alice", confirm_token="alice")

        # redis 失败应记到 failures
        assert any(name == "redis" for name, msg in report.failures)

    @pytest.mark.asyncio
    async def test_delete_influx_failure_recorded(self, monkeypatch):
        """delete_user_data: Influx 操作失败时记 failures（line 255-256）。"""
        from rhythmind.privacy import service as svc_mod

        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)
        mock_sess.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, [])
        mock_redis.aclose = AsyncMock()

        svc = svc_mod.PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )
        # _delete_influx_points 抛错
        svc._delete_influx_points = AsyncMock(
            side_effect=Exception("influx connection refused")
        )  # type: ignore[method-assign]
        svc._purge_qmd_namespaces = AsyncMock()  # type: ignore[method-assign]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            report = await svc.delete_user_data("alice", confirm_token="alice")

        # influxdb 失败应记到 failures
        assert any(name == "influxdb" for name, _ in report.failures)

    @pytest.mark.asyncio
    async def test_delete_qmd_failure_recorded(self, monkeypatch):
        """delete_user_data: QMD purge 失败时记 failures（line 264-265）。"""
        from rhythmind.privacy import service as svc_mod

        mock_sess = AsyncMock()
        mock_sess.__aenter__ = AsyncMock(return_value=mock_sess)
        mock_sess.__aexit__ = AsyncMock(return_value=False)
        mock_sess.execute = AsyncMock(return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        ))

        mock_redis = AsyncMock()
        mock_redis.scan.return_value = (0, [])
        mock_redis.aclose = AsyncMock()

        svc = svc_mod.PrivacyService(
            session_factory=lambda: mock_sess,
            redis_client=mock_redis,
        )
        svc._delete_influx_points = AsyncMock(return_value=True)  # type: ignore[method-assign]
        # QMD purge 抛错
        svc._purge_qmd_namespaces = AsyncMock(
            side_effect=Exception("qmd timeout")
        )  # type: ignore[method-assign]

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            report = await svc.delete_user_data("alice", confirm_token="alice")

        # qmd 失败应记到 failures
        assert any(name == "qmd" for name, _ in report.failures)

    @pytest.mark.asyncio
    async def test_count_influx_points_lazy_init_creates_client(self, monkeypatch):
        """_count_influx_points 内部 _influx 延迟初始化（line 290-291）：token 配置 + _influx=None 时创建 InfluxClient。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        # mock InfluxClient 构造
        mock_influx_instance = MagicMock()
        mock_influx_instance.query_range = AsyncMock(return_value={
            "field1": MagicMock(values=[1, 2, 3]),
        })

        with patch("rhythmind.adapters.influx_client.InfluxClient", return_value=mock_influx_instance) as mock_ctor:
            svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
            # svc._influx is None by default → 触发延迟初始化
            assert svc._influx is None
            count = await svc._count_influx_points("alice")

        # InfluxClient 构造函数被调用一次
        mock_ctor.assert_called_once()
        # svc._influx 被缓存
        assert svc._influx is mock_influx_instance
        # 返回值正常（累加 values）
        assert count == 3

    @pytest.mark.asyncio
    async def test_delete_influx_points_lazy_init_creates_client(self, monkeypatch):
        """_delete_influx_points 内部 _influx 延迟初始化（line 312-313 + 316 成功返回 True）。"""
        from rhythmind.privacy import service as svc_mod

        monkeypatch.setattr(svc_mod.settings, "influxdb_token", "test-token")

        mock_influx_instance = MagicMock()
        mock_influx_instance.delete_user_data = AsyncMock(return_value=None)

        with patch("rhythmind.adapters.influx_client.InfluxClient", return_value=mock_influx_instance) as mock_ctor:
            svc = svc_mod.PrivacyService(session_factory=lambda: AsyncMock())
            assert svc._influx is None  # 触发延迟初始化
            ok = await svc._delete_influx_points("alice")

        mock_ctor.assert_called_once()
        assert svc._influx is mock_influx_instance
        assert ok is True
