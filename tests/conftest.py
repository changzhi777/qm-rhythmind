"""
tests/conftest.py — 全局测试配置与 fixtures

设计原则：
  - 每个测试使用独立 SQLite in-memory DB，完全隔离
  - QMDClient 用 pytest-httpx mock，不依赖真实 QMD 服务
  - Redis LoopGuard 用 fakeredis 替代
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

# 强制设置测试环境（在任何 rhythmind import 之前）
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("QMD_URL", "http://localhost:8181")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("LITELLM_URL", "http://localhost:4000")
# 集成测试默认放行明文 Bearer（仅 ENV != prod 生效）
os.environ.setdefault("DEV_AUTH_BYPASS", "true")
os.environ.setdefault("ENFORCE_MODEL_PLATFORM", "false")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import rhythmind.core.memory.manager as mem_manager
from rhythmind.core.memory.models import Base


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    """每个测试前重建内存数据库，确保隔离。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 替换全局 session factory
    session_factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    mem_manager.AsyncSessionLocal = session_factory

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def user_id() -> str:
    return "test_user_001"


@pytest.fixture
def session_id() -> str:
    return "sess_abc123"
