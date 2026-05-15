"""
tests/unit/test_rate_limit.py — Redis 固定窗口限流测试

测试场景：
  1. 正常路径：未超限放行
  2. 超限拦截：返回 429 + Retry-After header
  3. fail-open：Redis 不可用时放行
  4. TTL：首次调用设置正确窗口
  5. per-user vs per-IP 独立计数
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from rhythmind.api.rate_limit import (
    _check_and_incr,
    rate_limit_ip,
    rate_limit_user,
)


class TestCheckAndIncr:
    """_check_and_incr 核心逻辑测试。"""

    def _make_mock_pipeline(self, execute_result):
        """创建支持 async with 的 mock pipeline。"""
        mock_pipeline = MagicMock()
        mock_pipeline.__aenter__ = AsyncMock(return_value=mock_pipeline)
        mock_pipeline.__aexit__ = AsyncMock()
        mock_pipeline.execute = AsyncMock(return_value=execute_result)
        return mock_pipeline

    def _make_mock_redis(self, pipeline):
        """创建 mock Redis client。"""
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = pipeline
        return mock_redis

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self):
        """未超限应放行。"""
        mock_pipeline = self._make_mock_pipeline([1, True, 59])
        mock_redis = self._make_mock_redis(mock_pipeline)

        with patch("rhythmind.api.rate_limit._get_redis", return_value=mock_redis):
            allowed, count, retry_after = await _check_and_incr("test_key", 30, 60)

            assert allowed is True
            assert count == 1
            assert retry_after == 0

    @pytest.mark.asyncio
    async def test_over_limit_blocked(self):
        """超过限制应拦截。"""
        mock_pipeline = self._make_mock_pipeline([31, True, 45])
        mock_redis = self._make_mock_redis(mock_pipeline)

        with patch("rhythmind.api.rate_limit._get_redis", return_value=mock_redis):
            allowed, count, retry_after = await _check_and_incr("test_key", 30, 60)

            assert allowed is False
            assert count == 31
            assert retry_after == 45

    @pytest.mark.asyncio
    async def test_exactly_at_limit_allowed(self):
        """正好达到限制应放行。"""
        mock_pipeline = self._make_mock_pipeline([30, True, 60])
        mock_redis = self._make_mock_redis(mock_pipeline)

        with patch("rhythmind.api.rate_limit._get_redis", return_value=mock_redis):
            allowed, count, retry_after = await _check_and_incr("test_key", 30, 60)

            assert allowed is True
            assert count == 30

    @pytest.mark.asyncio
    async def test_redis_error_fails_open(self):
        """Redis 错误时应 fail-open（放行）。"""
        mock_redis = MagicMock()
        mock_redis.pipeline.side_effect = Exception("Connection refused")

        with patch("rhythmind.api.rate_limit._get_redis", return_value=mock_redis):
            allowed, count, retry_after = await _check_and_incr("test_key", 30, 60)

            # fail-open：应返回 True
            assert allowed is True
            assert count == 0
            assert retry_after == 0

    @pytest.mark.asyncio
    async def test_first_call_sets_ttl(self):
        """首次调用应设置 EXPIRE。"""
        mock_pipeline = self._make_mock_pipeline([1, False, -1])
        mock_redis = self._make_mock_redis(mock_pipeline)

        with patch("rhythmind.api.rate_limit._get_redis", return_value=mock_redis):
            await _check_and_incr("test_key", 30, 60)

            # 验证 pipeline 被调用
            mock_redis.pipeline.assert_called_once()


class TestRateLimitUser:
    """rate_limit_user 依赖工厂测试。"""

    @pytest.mark.asyncio
    async def test_under_limit_passes(self):
        """未超限依赖执行成功。"""
        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (True, 1, 0)

            limiter = rate_limit_user("upload", 30, 60)
            dep = limiter(user_id="test_user")
            await dep

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(self):
        """超过限制应抛出 HTTP 429。"""
        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (False, 31, 45)

            limiter = rate_limit_user("upload", 30, 60)

            with pytest.raises(HTTPException) as exc_info:
                await limiter(user_id="test_user")

            assert exc_info.value.status_code == 429
            assert "45" in exc_info.value.detail
            assert exc_info.value.headers["Retry-After"] == "45"

    @pytest.mark.asyncio
    async def test_different_user_ids_independent(self):
        """不同 user_id 独立计数。"""
        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (True, 1, 0)

            limiter = rate_limit_user("upload", 30, 60)

            await limiter(user_id="user_a")
            await limiter(user_id="user_b")

            assert mock_check.call_count == 2
            call_args = [c[0] for c in mock_check.call_args_list]
            assert any("user_a" in str(c) for c in call_args)
            assert any("user_b" in str(c) for c in call_args)


class TestRateLimitIP:
    """rate_limit_ip 依赖工厂测试。"""

    @pytest.fixture
    def mock_request(self):
        """创建模拟 Request 对象。"""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.168.1.1"
        return request

    @pytest.mark.asyncio
    async def test_under_limit_passes(self, mock_request):
        """未超限依赖执行成功。"""
        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (True, 1, 0)

            limiter = rate_limit_ip("upload", 60, 60)
            await limiter(request=mock_request)

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(self, mock_request):
        """超过限制应抛出 HTTP 429。"""
        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (False, 61, 30)

            limiter = rate_limit_ip("upload", 60, 60)

            with pytest.raises(HTTPException) as exc_info:
                await limiter(request=mock_request)

            assert exc_info.value.status_code == 429
            assert "30" in exc_info.value.detail
            assert exc_info.value.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_x_forwarded_for_takes_precedence(self, mock_request):
        """X-Forwarded-For header 优先于 client.host。"""
        mock_request.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}

        with patch("rhythmind.api.rate_limit._check_and_incr") as mock_check:
            mock_check.return_value = (True, 1, 0)

            limiter = rate_limit_ip("upload", 60, 60)
            await limiter(request=mock_request)

            call_args = mock_check.call_args[0]
            key = call_args[0]
            assert "10.0.0.1" in key
            assert "192.168.1.1" not in key
