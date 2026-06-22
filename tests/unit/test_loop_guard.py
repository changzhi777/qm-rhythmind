"""
tests/unit/test_loop_guard.py — LoopGuard 防循环节流测试

测试场景：
  1. 正常路径：未超限返回 False
  2. 超限拦截：超过 max_calls 返回 True
  3. fail-open：Redis 不可用时放行
  4. reset：手动重置后恢复正常
  5. TTL：首次调用设置正确 TTL
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from rhythmind.orchestrator.loop_guard import LoopGuard


class TestLoopGuard:
    """LoopGuard 核心逻辑测试（mock Redis）。"""

    def _make_mock_redis(self, incr_result, ttl_result):
        """创建 mock Redis client with pipeline。"""
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.incr = MagicMock()
        mock_pipeline.ttl = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[str(incr_result), ttl_result])

        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_redis.expire = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_redis.aclose = AsyncMock()
        return mock_redis, mock_pipeline

    @pytest.fixture
    def guard(self) -> LoopGuard:
        return LoopGuard()

    @pytest.mark.asyncio
    async def test_under_limit_returns_false(self, guard: LoopGuard):
        """未超限时应放行。"""
        mock_redis, _ = self._make_mock_redis(incr_result=1, ttl_result=60)
        guard._redis = mock_redis

        is_cooling = await guard.is_cooling_down("user", "intent")
        assert is_cooling is False

    @pytest.mark.asyncio
    async def test_over_limit_returns_true(self, guard: LoopGuard):
        """超过 max_calls 应拦截。"""
        mock_redis, _ = self._make_mock_redis(incr_result=6, ttl_result=60)
        guard._redis = mock_redis

        is_cooling = await guard.is_cooling_down("user", "intent")
        assert is_cooling is True

    @pytest.mark.asyncio
    async def test_different_intents_independent(self, guard: LoopGuard):
        """不同 intent 独立计数。"""
        mock_redis = MagicMock()
        mock_pipeline_a = MagicMock()
        mock_pipeline_a.__aenter__ = AsyncMock(return_value=mock_pipeline_a)
        mock_pipeline_a.__aexit__ = AsyncMock()
        mock_pipeline_a.execute = AsyncMock(return_value=["6", 60])

        mock_pipeline_b = MagicMock()
        mock_pipeline_b.__aenter__ = AsyncMock(return_value=mock_pipeline_b)
        mock_pipeline_b.__aexit__ = AsyncMock()
        mock_pipeline_b.execute = AsyncMock(return_value=["1", 60])

        mock_redis.pipeline = MagicMock(side_effect=[mock_pipeline_a, mock_pipeline_b])
        guard._redis = mock_redis

        # intent_a 超限
        assert await guard.is_cooling_down("user", "intent_a") is True
        # intent_b 未超限
        assert await guard.is_cooling_down("user", "intent_b") is False

    @pytest.mark.asyncio
    async def test_different_users_independent(self, guard: LoopGuard):
        """不同 user 独立计数。"""
        mock_redis = MagicMock()
        mock_pipeline_a = MagicMock()
        mock_pipeline_a.__aenter__ = AsyncMock(return_value=mock_pipeline_a)
        mock_pipeline_a.__aexit__ = AsyncMock()
        mock_pipeline_a.execute = AsyncMock(return_value=["6", 60])

        mock_pipeline_b = MagicMock()
        mock_pipeline_b.__aenter__ = AsyncMock(return_value=mock_pipeline_b)
        mock_pipeline_b.__aexit__ = AsyncMock()
        mock_pipeline_b.execute = AsyncMock(return_value=["1", 60])

        mock_redis.pipeline = MagicMock(side_effect=[mock_pipeline_a, mock_pipeline_b])
        guard._redis = mock_redis

        # user_a 超限
        assert await guard.is_cooling_down("user_a", "intent") is True
        # user_b 未超限
        assert await guard.is_cooling_down("user_b", "intent") is False

    @pytest.mark.asyncio
    async def test_reset_clears_counter(self, guard: LoopGuard):
        """reset 后计数器清零。"""
        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock()
        mock_redis.aclose = AsyncMock()
        guard._redis = mock_redis

        await guard.reset("user", "intent")
        mock_redis.delete.assert_called_once_with("loop:user:intent")

    @pytest.mark.asyncio
    async def test_close(self, guard: LoopGuard):
        """close 应关闭 Redis 连接。"""
        mock_redis = MagicMock()
        mock_redis.aclose = AsyncMock()
        guard._redis = mock_redis

        await guard.close()
        mock_redis.aclose.assert_called_once()


class TestLoopGuardFailOpen:
    """Redis 不可用时的 fail-open 行为测试。"""

    @pytest.fixture
    def guard(self) -> LoopGuard:
        return LoopGuard()

    @pytest.mark.asyncio
    async def test_redis_connection_error_fails_open(self, guard: LoopGuard):
        """Redis 连接错误时应 fail-open（返回 False）。"""
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.execute.side_effect = Exception("Connection refused")
        mock_redis.pipeline.return_value = mock_pipeline
        guard._redis = mock_redis

        result = await guard.is_cooling_down("user", "intent")
        assert result is False

    @pytest.mark.asyncio
    async def test_redis_pipeline_error_fails_open(self, guard: LoopGuard):
        """Redis pipeline 执行错误时应 fail-open。"""
        mock_redis = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.execute.side_effect = Exception("Redis error")
        mock_redis.pipeline.return_value = mock_pipeline
        guard._redis = mock_redis

        result = await guard.is_cooling_down("user", "intent")
        assert result is False


class TestLoopGuardTTL:
    """TTL 设置逻辑测试。"""

    @pytest.fixture
    def guard(self) -> LoopGuard:
        return LoopGuard()

    @pytest.mark.asyncio
    async def test_ttl_set_on_first_call(self, guard: LoopGuard):
        """首次写入时应设置 EXPIRE。"""
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        # ttl=-1 表示 key 不存在（首次调用）
        mock_pipeline.execute = AsyncMock(return_value=["1", -1])

        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_redis.expire = AsyncMock()
        guard._redis = mock_redis

        await guard.is_cooling_down("user", "intent")

        # 验证 expire 被调用（首次写入且 key 无 TTL 时）
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_ttl_not_reset_on_subsequent_calls(self, guard: LoopGuard):
        """后续调用（TTL 已存在）不应重置 expire。"""
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        # ttl=3600 表示 key 已有过期时间
        mock_pipeline.execute = AsyncMock(return_value=["2", 3600])

        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = mock_pipeline
        mock_redis.expire = AsyncMock()
        guard._redis = mock_redis

        await guard.is_cooling_down("user", "intent")

        # 验证 expire 不被调用（TTL 已存在）
        mock_redis.expire.assert_not_called()


# ── 辅助函数 + 边界（line 60/63-65/82/53）────────────────────────────────

class TestParseTieredLimits:
    """_parse_tiered_limits: 解析 settings.loop_guard_tiered_limits JSON。"""

    def test_empty_raw_returns_empty_dict(self, monkeypatch):
        """raw 为空时（line 60）返 {}。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(loop_guard.settings, "loop_guard_tiered_limits", "")
        assert loop_guard._parse_tiered_limits() == {}

    def test_valid_json_returns_dict(self, monkeypatch):
        """合法 JSON 字符串正确解析为 dict。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(
            loop_guard.settings, "loop_guard_tiered_limits",
            '{"greeting": 10, "query": 30, "__default__": 5}',
        )
        result = loop_guard._parse_tiered_limits()
        assert result == {"greeting": 10, "query": 30, "__default__": 5}

    def test_invalid_json_returns_empty_and_logs_warning(self, monkeypatch, caplog):
        """非法 JSON（line 63-65）→ logger.warning + 返 {}。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(
            loop_guard.settings, "loop_guard_tiered_limits",
            "{greeting: 10, invalid}",
        )
        with caplog.at_level("WARNING"):
            result = loop_guard._parse_tiered_limits()
        assert result == {}
        assert any("parse_error" in r.message for r in caplog.records)


class TestGetLimit:
    """LoopGuard._get_limit: tiered_limits 命中或 fallback。"""

    def test_returns_tiered_limit_when_intent_matched(self, monkeypatch):
        """intent 在 tiered_limits 中时返其值（line 81-82）。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(
            loop_guard.settings, "loop_guard_tiered_limits",
            '{"greeting": 10, "query": 30, "__default__": 5}',
        )
        guard = LoopGuard(redis_url="redis://localhost:6379/0")
        assert guard._get_limit("greeting") == 10
        assert guard._get_limit("query") == 30

    def test_falls_back_to_default_when_intent_unknown(self, monkeypatch):
        """intent 不在 tiered 中时 fallback 到 __default__（line 83）。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(
            loop_guard.settings, "loop_guard_tiered_limits",
            '{"greeting": 10, "__default__": 5}',
        )
        guard = LoopGuard(redis_url="redis://localhost:6379/0")
        assert guard._get_limit("unknown_intent") == 5

    def test_falls_back_to_max_calls_when_no_default_key(self, monkeypatch):
        """tiered_limits 空时 fallback 到 settings.loop_guard_max_calls。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(loop_guard.settings, "loop_guard_tiered_limits", "")
        monkeypatch.setattr(loop_guard.settings, "loop_guard_max_calls", 7)
        guard = LoopGuard(redis_url="redis://localhost:6379/0")
        assert guard._get_limit("any") == 7


class TestRecordCall:
    """_record_call: Prometheus Counter 指标记录（line 51-53）。"""

    def test_record_call_with_prometheus(self, monkeypatch):
        """prometheus_client 已装时（_LOOP_GUARD_CALLS != None）正确 inc。"""
        from rhythmind.orchestrator import loop_guard

        mock_counter = MagicMock()
        monkeypatch.setattr(loop_guard, "_LOOP_GUARD_CALLS", mock_counter)

        loop_guard._record_call("greeting", "allowed")

        mock_counter.labels.assert_called_once_with(intent="greeting", result="allowed")
        mock_counter.labels.return_value.inc.assert_called_once()

    def test_record_call_no_op_when_prometheus_unavailable(self, monkeypatch):
        """prometheus_client 未装时（_LOOP_GUARD_CALLS=None）no-op，不抛异常。"""
        from rhythmind.orchestrator import loop_guard

        monkeypatch.setattr(loop_guard, "_LOOP_GUARD_CALLS", None)
        # 不应抛异常
        loop_guard._record_call("greeting", "throttled")
