"""
tests/unit/test_agent_pool.py — AgentPool LRU 缓存测试

测试场景：
  1. acquire 返回现有 bundle（缓存命中）
  2. acquire 创建新 bundle（缓存未命中）
  3. LRU 驱逐：容量满时淘汰最久未使用
  4. TTL 过期：超过 ttl_seconds 的 bundle 被重建
  5. invalidate 强制淘汰
  6. purge_expired 清理过期条目
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from rhythmind.orchestrator.pool import AgentBundle, AgentPool


class TestAgentPoolAcquire:
    """acquire 上下文管理器测试。"""

    @pytest.fixture
    def pool(self) -> AgentPool:
        return AgentPool(max_users=3, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_acquire_creates_new_bundle_on_miss(self, pool: AgentPool):
        """首次 acquire 为新用户创建 bundle。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            mock_create.return_value = AgentBundle(
                user_id="new_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )

            async with pool.acquire("new_user") as bundle:
                assert bundle.user_id == "new_user"
                assert pool.size == 1

    @pytest.mark.asyncio
    async def test_acquire_returns_cached_bundle_on_hit(self, pool: AgentPool):
        """同一用户的第二次 acquire 返回缓存的 bundle。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            mock_create.return_value = AgentBundle(
                user_id="cached_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )

            # 第一次
            async with pool.acquire("cached_user") as bundle1:
                pass

            # 第二次
            async with pool.acquire("cached_user") as bundle2:
                # 应该是同一个对象
                assert bundle1 is bundle2
                assert pool.size == 1  # 不应创建新 bundle

    @pytest.mark.asyncio
    async def test_acquire_touches_last_used(self, pool: AgentPool):
        """acquire 归还后更新 last_used 时间戳。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            mock_bundle = AgentBundle(
                user_id="touch_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = mock_bundle

            initial_last_used = mock_bundle.last_used

            # 短暂等待
            await asyncio.sleep(0.01)

            async with pool.acquire("touch_user"):
                pass

            # 归还后 last_used 应该被更新
            assert mock_bundle.last_used >= initial_last_used


class TestAgentPoolLRUEviction:
    """LRU 驱逐逻辑测试。"""

    @pytest.fixture
    def pool(self) -> AgentPool:
        return AgentPool(max_users=3, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_pool_evicts_lru_when_full(self, pool: AgentPool):
        """容量满时驱逐最久未使用的用户。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            # 创建 3 个 mock bundle
            bundles = {}
            for uid in ["user_a", "user_b", "user_c"]:
                bundles[uid] = AgentBundle(
                    user_id=uid,
                    metrics=AsyncMock(),
                    data=AsyncMock(),
                    coach=AsyncMock(),
                )
            mock_create.side_effect = lambda uid: bundles.setdefault(
                uid,
                AgentBundle(user_id=uid, metrics=AsyncMock(), data=AsyncMock(), coach=AsyncMock()),
            )

            # 填满池子
            async with pool.acquire("user_a"):
                pass
            async with pool.acquire("user_b"):
                pass
            async with pool.acquire("user_c"):
                pass

            assert pool.size == 3

            # 现在加入 user_d，最久未使用的 user_a 应被驱逐
            async with pool.acquire("user_d"):
                pass

            assert pool.size == 3
            # user_a 应该已被驱逐
            assert "user_a" not in pool._pool
            # user_b, user_c, user_d 应该还在
            assert "user_b" in pool._pool
            assert "user_c" in pool._pool
            assert "user_d" in pool._pool

    @pytest.mark.asyncio
    async def test_recently_used不会被_evicted(self, pool: AgentPool):
        """最近使用的用户不会被驱逐。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundles = {}
            for uid in ["user_x", "user_y", "user_z"]:
                bundles[uid] = AgentBundle(
                    user_id=uid,
                    metrics=AsyncMock(),
                    data=AsyncMock(),
                    coach=AsyncMock(),
                )
            mock_create.side_effect = lambda uid: bundles.setdefault(
                uid,
                AgentBundle(user_id=uid, metrics=AsyncMock(), data=AsyncMock(), coach=AsyncMock()),
            )

            # 填满池子
            async with pool.acquire("user_x"):
                pass
            async with pool.acquire("user_y"):
                pass
            async with pool.acquire("user_z"):
                pass

            # 再次使用 user_x（变为最近使用）
            async with pool.acquire("user_x"):
                pass

            # 加入 user_new，user_y（最旧）应被驱逐
            async with pool.acquire("user_new"):
                pass

            assert "user_x" in pool._pool  # 最近使用，不应被驱逐
            assert "user_y" not in pool._pool  # 最旧，应被驱逐


class TestAgentPoolTTL:
    """TTL 过期逻辑测试。"""

    @pytest.mark.asyncio
    async def test_ttl_expired_bundle_recreated(self):
        """超过 TTL 的 bundle 被重建而非返回。"""
        pool = AgentPool(max_users=3, ttl_seconds=0.1)  # 100ms TTL

        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundle1 = AgentBundle(
                user_id="ttl_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = bundle1

            # 第一次获取
            async with pool.acquire("ttl_user"):
                pass

            assert mock_create.call_count == 1

            # 等待 TTL 过期
            await asyncio.sleep(0.15)

            # 再次获取，应该创建新 bundle
            async with pool.acquire("ttl_user"):
                pass

            assert mock_create.call_count == 2

    @pytest.mark.asyncio
    async def test_ttl_within_window_not_expired(self):
        """TTL 内未过期的 bundle 不被重建。"""
        pool = AgentPool(max_users=3, ttl_seconds=60)

        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundle = AgentBundle(
                user_id="fresh_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = bundle

            async with pool.acquire("fresh_user"):
                pass

            # 立即再次使用
            async with pool.acquire("fresh_user"):
                pass

            # 应该只创建一次
            assert mock_create.call_count == 1


class TestAgentPoolInvalidate:
    """invalidate 强制淘汰测试。"""

    @pytest.fixture
    def pool(self) -> AgentPool:
        return AgentPool(max_users=3, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_invalidate_removes_user(self, pool: AgentPool):
        """invalidate 强制移除用户的 bundle。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundle = AgentBundle(
                user_id="to_remove",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = bundle

            async with pool.acquire("to_remove"):
                pass

            assert pool.size == 1

            await pool.invalidate("to_remove")

            assert pool.size == 0

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_no_error(self, pool: AgentPool):
        """invalidate 不存在的用户不报错。"""
        await pool.invalidate("nonexistent_user")
        # 不应抛出异常


class TestAgentPoolPurgeExpired:
    """purge_expired 测试。"""

    @pytest.fixture
    def pool(self) -> AgentPool:
        return AgentPool(max_users=10, ttl_seconds=0.1)  # 100ms TTL

    @pytest.mark.asyncio
    async def test_purge_expired_returns_count(self, pool: AgentPool):
        """purge_expired 返回清理的条目数量。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundles = {}
            for uid in ["expire_1", "expire_2", "expire_3"]:
                bundles[uid] = AgentBundle(
                    user_id=uid,
                    metrics=AsyncMock(),
                    data=AsyncMock(),
                    coach=AsyncMock(),
                )
            mock_create.side_effect = lambda uid: bundles.setdefault(
                uid,
                AgentBundle(user_id=uid, metrics=AsyncMock(), data=AsyncMock(), coach=AsyncMock()),
            )

            # 创建 3 个 bundle
            for uid in ["expire_1", "expire_2", "expire_3"]:
                async with pool.acquire(uid):
                    pass

            # 等待 TTL 过期
            await asyncio.sleep(0.15)

            # purge
            purged = await pool.purge_expired()

            assert purged == 3
            assert pool.size == 0

    @pytest.mark.asyncio
    async def test_purge_nonexpired_returns_zero(self, pool: AgentPool):
        """未过期的 bundle 不被清理。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundle = AgentBundle(
                user_id="alive",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = bundle

            async with pool.acquire("alive"):
                pass

            purged = await pool.purge_expired()

            assert purged == 0
            assert pool.size == 1


class TestAgentBundle:
    """AgentBundle 数据类测试。"""

    def test_touch_updates_last_used(self):
        """touch() 更新 last_used 时间戳。"""
        bundle = AgentBundle(
            user_id="test",
            metrics=AsyncMock(),
            data=AsyncMock(),
            coach=AsyncMock(),
        )
        initial = bundle.last_used
        time.sleep(0.01)
        bundle.touch()
        assert bundle.last_used > initial

    def test_age_seconds(self):
        """age_seconds 返回 bundle 创建后经过的时间。"""
        bundle = AgentBundle(
            user_id="test",
            metrics=AsyncMock(),
            data=AsyncMock(),
            coach=AsyncMock(),
        )
        time.sleep(0.01)
        assert bundle.age_seconds >= 0.01

    def test_idle_seconds(self):
        """idle_seconds 返回最近使用后经过的时间。"""
        bundle = AgentBundle(
            user_id="test",
            metrics=AsyncMock(),
            data=AsyncMock(),
            coach=AsyncMock(),
        )
        time.sleep(0.01)
        assert bundle.idle_seconds >= 0.01


class TestAgentPoolStats:
    """stats() 诊断信息测试。"""

    @pytest.fixture
    def pool(self) -> AgentPool:
        return AgentPool(max_users=5, ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_stats_returns_pool_state(self, pool: AgentPool):
        """stats 返回正确的池状态。"""
        with patch("rhythmind.orchestrator.pool.AgentPool._create_bundle") as mock_create:
            bundle = AgentBundle(
                user_id="stat_user",
                metrics=AsyncMock(),
                data=AsyncMock(),
                coach=AsyncMock(),
            )
            mock_create.return_value = bundle

            async with pool.acquire("stat_user"):
                pass

            stats = pool.stats()

            assert stats["pool_size"] == 1
            assert stats["max_users"] == 5
            assert stats["ttl_seconds"] == 60
            assert len(stats["entries"]) == 1
            assert stats["entries"][0]["user_id"] == "stat_user"
