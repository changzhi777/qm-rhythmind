# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/memory/manager.py — MemoryManager（异步 CRUD + namespace 隔离）

数据库：PostgreSQL（asyncpg 驱动，JSONB 原生存储）
测试：  SQLite in-memory（with_variant 自动降级）

连接池策略：
  生产 PG  → pool_size=10, max_overflow=20, pool_timeout=30s
  测试 SQLite → NullPool（每次连接，无池，避免 asyncio 跨协程共享）

upsert 策略：
  PostgreSQL INSERT ... ON CONFLICT (namespace, key) DO UPDATE
  一条 SQL 完成幂等写入，无需先查后写的 race condition。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
import json
from typing import Any

from sqlalchemy import NullPool, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from rhythmind.config import settings

from .models import AgentMemory, Base
from .types import MemoryEntry, MemoryRecallResult, MemoryType

logger = logging.getLogger(__name__)


# ── 引擎 & Session 工厂（模块级单例）─────────────────────────────────────

def _build_engine() -> Any:
    """按 DATABASE_URL 构建对应引擎，自动区分 PG / SQLite。"""
    url = settings.database_url
    is_sqlite = "sqlite" in url

    kwargs: dict[str, Any] = {
        "echo": settings.debug,
        "pool_pre_ping": settings.pg_pool_pre_ping if not is_sqlite else False,
    }
    if is_sqlite:
        # 单元测试：NullPool，每次测试独立连接，无跨 test 共享
        kwargs["poolclass"] = NullPool
    else:
        # PostgreSQL 生产连接池
        kwargs.update(
            pool_size=settings.pg_pool_size,
            max_overflow=settings.pg_pool_max_overflow,
            pool_timeout=settings.pg_pool_timeout,
            pool_recycle=settings.pg_pool_recycle,
            # asyncpg + SQL_ASCII 数据库下，json.dumps 的 \u 转义序列
            # 会触发 UntranslatableCharacterError。ensure_ascii=False
            # 让 JSON 直接以 UTF-8 字节发送，避开字符集转换。
            json_serializer=lambda obj: json.dumps(obj, ensure_ascii=False),
        )
    return create_async_engine(url, **kwargs)


_engine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """
    在应用启动时建表（开发 / 测试用）。

    生产环境使用 Alembic 做 migration，不应调用此函数。
    通过 settings.env 区分：dev/test → 建表；prod → 跳过。
    """
    if settings.env == "prod":
        logger.warning(
            "init_db() called in prod — skipping. Use `alembic upgrade head` instead."
        )
        return
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("init_db: tables created (env=%s)", settings.env)


# ── upsert SQL 构建 ─────────────────────────────────────────────────────

def _build_upsert(is_sqlite: bool) -> Any:
    """返回对应方言的 insert 函数（延迟 import，避免 PG 依赖在纯 SQLite 环境报错）。"""
    if is_sqlite:
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert


class MemoryManager:
    """
    单个 Agent 的记忆管理器。

    每个 HermesBase 实例持有一个 MemoryManager，
    user_id + agent 确定所有操作的 namespace 前缀。
    """

    def __init__(self, user_id: str, agent: str) -> None:
        self.user_id = user_id
        self.agent = agent
        self._prefix = f"user.{self._safe(user_id)}.{self._safe(agent)}"
        self._is_sqlite = "sqlite" in settings.database_url

    # ── 公共接口 ──────────────────────────────────────────────────────────

    async def recall(
        self,
        task_type: str,
        mem_types: list[MemoryType] | None = None,
        limit: int = 20,
    ) -> MemoryRecallResult:
        """
        召回当前 agent 的历史记忆。

        Args:
            task_type:  (保留参数，Phase 2 做语义过滤)
            mem_types:  按类型过滤，None 返回全部
            limit:      最大返回条数
        """
        async with AsyncSessionLocal() as session:
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == self.user_id,
                    AgentMemory.agent == self.agent,
                    AgentMemory.deleted_at.is_(None),
                    (AgentMemory.expires_at.is_(None))
                    | (AgentMemory.expires_at > datetime.now(tz=UTC)),
                )
                .order_by(AgentMemory.updated_at.desc())
                .limit(limit)
            )
            if mem_types:
                stmt = stmt.where(
                    AgentMemory.mem_type.in_([t.value for t in mem_types])
                )
            rows = (await session.execute(stmt)).scalars().all()

        entries = [self._row_to_entry(r) for r in rows]
        return MemoryRecallResult(entries=entries, total=len(entries))

    async def write(
        self,
        key: str,
        value: Any,
        mem_type: MemoryType | str = MemoryType.PROJECT,
        confidence: float = 1.0,
        ttl_hours: int | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """
        幂等 upsert。

        PostgreSQL：INSERT ... ON CONFLICT (namespace, key) DO UPDATE
        SQLite：     INSERT OR REPLACE（测试用）

        同一 (namespace, key) 存在时只更新 value/meta，
        不修改 created_at，保留历史时间戳。
        """
        if isinstance(mem_type, str):
            mem_type = MemoryType(mem_type)

        namespace = f"{self._prefix}.{self._safe(key)}"
        now = datetime.now(tz=UTC)
        expires_at: datetime | None = (
            now + timedelta(hours=ttl_hours) if ttl_hours else None
        )

        # JSONB / JSONText 兼容写法：直接传 Python 对象
        value_payload = value
        tags_payload = tags or []

        insert = _build_upsert(self._is_sqlite)
        stmt = insert(AgentMemory).values(
            namespace=namespace,
            user_id=self.user_id,
            agent=self.agent,
            key=key,
            value_json=value_payload,
            mem_type=mem_type.value,
            confidence=confidence,
            tags=tags_payload,
            expires_at=expires_at,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["namespace", "key"],
            set_={
                "value_json": stmt.excluded.value_json,
                "mem_type":   stmt.excluded.mem_type,
                "confidence": stmt.excluded.confidence,
                "tags":       stmt.excluded.tags,
                "expires_at": stmt.excluded.expires_at,
                "updated_at": now,
            },
        )

        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(stmt)

        logger.debug("memory.write ns=%s key=%s type=%s", namespace, key, mem_type)

    async def update(self, updates: dict[str, Any]) -> None:
        """批量 upsert，供 HermesBase.run() 的 memory_updates 字典使用。"""
        for key, value in updates.items():
            await self.write(key, value)

    async def delete(self, key: str) -> None:
        """软删除（设置 deleted_at）。"""
        namespace = f"{self._prefix}.{self._safe(key)}"
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                update(AgentMemory)
                .where(
                    AgentMemory.namespace == namespace,
                    AgentMemory.key == key,
                )
                .values(deleted_at=datetime.now(tz=UTC))
            )

    async def purge_expired(self) -> int:
        """
        硬删除所有过期条目（周期性清理任务调用）。

        Returns:
            删除的行数。
        """
        async with AsyncSessionLocal() as session, session.begin():
            result = await session.execute(
                delete(AgentMemory).where(
                    AgentMemory.expires_at < datetime.now(tz=UTC)
                )
            )
        count: int = result.rowcount  # type: ignore[assignment]
        logger.info("memory.purge_expired deleted=%d", count)
        return count

    # ── 内部工具 ──────────────────────────────────────────────────────────

    @staticmethod
    def _safe(s: str) -> str:
        """仅保留 [a-z0-9_-]，防止 namespace 注入。"""
        return "".join(
            c if c.isalnum() or c in "-_" else "_" for c in s.lower()
        )

    @staticmethod
    def _row_to_entry(row: AgentMemory) -> MemoryEntry:
        return MemoryEntry(
            namespace=row.namespace,
            key=row.key,
            value=row.value,          # JSONB 已反序列化为 Python 对象
            mem_type=MemoryType(row.mem_type),
            confidence=row.confidence,
            created_at=row.created_at,
            updated_at=row.updated_at,
            expires_at=row.expires_at,
            tags=row.tag_list,
        )
