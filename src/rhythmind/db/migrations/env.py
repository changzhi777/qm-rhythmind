# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
db/migrations/env.py — Alembic 异步迁移环境

支持 asyncpg（PostgreSQL async 驱动）的 Alembic 迁移。
Alembic 本身是同步的，通过 run_sync 桥接 asyncio。

使用方式：
  # 在项目根目录执行
  alembic upgrade head
  alembic revision --autogenerate -m "add new column"
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 加载应用配置（必须在 import models 之前）
import os
os.environ.setdefault("ENV", "dev")

from rhythmind.config import settings
from rhythmind.core.memory.models import Base  # 导入所有 ORM 模型

# Alembic Config 对象
config = context.config

# 设置 logging（来自 alembic.ini）
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 将所有 ORM 模型的 metadata 注册给 Alembic（autogenerate 依赖此）
target_metadata = Base.metadata

# 从 settings 注入 database_url（覆盖 alembic.ini 中的空值）
# asyncpg URL 需要替换为 sync 驱动用于 Alembic 内部检查
def _get_sync_url() -> str:
    """将 asyncpg URL 转为 psycopg2 URL（Alembic 检查用）。"""
    url = settings.database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def run_migrations_offline() -> None:
    """
    离线模式：不需要数据库连接，直接生成 SQL 脚本。

    用途：生成可在生产数据库手动执行的 SQL 文件。
    """
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # PostgreSQL 特定：使用 schema 过滤避免系统表干扰
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：通过 asyncpg 连接数据库执行迁移。"""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = settings.database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 迁移只需单连接，不需要池
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口（同步包装异步）。"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
