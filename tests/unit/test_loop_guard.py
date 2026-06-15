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
