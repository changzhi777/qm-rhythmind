# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/memory/fact_manager.py — 健康时序知识图谱管理器

基于 MemPalace 的 KG 设计理念，在 RHYTHMIND 的 PostgreSQL 层实现。

核心语义：
  每条 HealthFact = <user_id, subject, predicate, object> 的有效时间窗口。
  写入新事实时，自动 invalidate 同 subject+predicate 的旧有效记录。
  历史轨迹完整保留（软删除语义：设置 valid_until，不物理删除）。

典型用法：
  # 记录训练目标
  await fm.write_fact(user_id, "user_goal", "targets",
                      {"goal": "马拉松", "deadline": "2027-03"}, "coach_agent")

  # 康复后标记伤病过期
  await fm.invalidate_by_subject(user_id, "injury", "restricts")

  # 查询当前有效目标
  facts = await fm.query_current(user_id, "user_goal")
  goal = facts[0].object if facts else None
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from rhythmind.core.cache import FactCache
from rhythmind.core.memory.models import HealthFact


def _get_session() -> AsyncSession:
    """懒导入 AsyncSessionLocal，避免模块加载时触发 PG 引擎构建。"""
    from rhythmind.core.memory.manager import AsyncSessionLocal  # noqa: PLC0415
    return AsyncSessionLocal()

logger = logging.getLogger(__name__)


class FactManager:
    """
    健康时序知识图谱管理器。

    无状态，可在多 Agent 间共享同一实例。
    所有方法自管理 Session 生命周期（无需调用方手动管理事务）。
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    # ── 写入（自动 invalidate 旧值）──────────────────────────────────────────

    async def write_fact(
        self,
        subject: str,
        predicate: str,
        object_value: Any,
        source: str = "system",
        confidence: float = 1.0,
        valid_from: datetime | None = None,
    ) -> HealthFact:
        """
        写入新事实，自动 invalidate 同 subject+predicate 的所有旧有效记录。

        这是最常用的接口：调用后，总是只有一条当前有效记录。
        需要保留多条并行有效记录时，使用 write_fact_additive()。

        Returns:
            新写入的 HealthFact 实例。
        """
        now = valid_from or datetime.now(tz=UTC)
        async with _get_session() as session, session.begin():
            # 1. invalidate 所有同 subject+predicate 的旧记录
            await session.execute(
                update(HealthFact)
                .where(
                    and_(
                        HealthFact.user_id == self.user_id,
                        HealthFact.subject == subject,
                        HealthFact.predicate == predicate,
                        HealthFact.valid_until.is_(None),
                    )
                )
                .values(valid_until=now)
            )

            # 2. 写入新事实
            fact = HealthFact(
                user_id=self.user_id,
                subject=subject,
                predicate=predicate,
                object_json=object_value,
                source=source,
                confidence=confidence,
                valid_from=now,
                valid_until=None,  # 当前有效
            )
            session.add(fact)
            await session.flush()
            await session.refresh(fact)

            logger.debug(
                "fact.write user=%s (%s, %s) id=%s",
                self.user_id, subject, predicate, fact.id,
            )
            # invalidate fact cache after write
            await FactCache.invalidate(self.user_id, subject, predicate)
            return fact

    async def write_fact_additive(
        self,
        subject: str,
        predicate: str,
        object_value: Any,
        source: str = "system",
        confidence: float = 1.0,
    ) -> HealthFact:
        """
        追加写入（不 invalidate 旧记录）。

        用于允许多条并行有效记录的场景，如：
          多个伤病部位同时有效 (injury, restricts, {area: 膝盖})
                               (injury, restricts, {area: 腰部})
        """
        async with _get_session() as session, session.begin():
            fact = HealthFact(
                user_id=self.user_id,
                subject=subject,
                predicate=predicate,
                object_json=object_value,
                source=source,
                confidence=confidence,
                valid_until=None,
            )
            session.add(fact)
            await session.flush()
            await session.refresh(fact)
            return fact

    # ── 过期（Invalidate）────────────────────────────────────────────────────

    async def invalidate_fact(self, fact_id: int) -> bool:
        """
        按 ID 将单条事实标记过期。

        Returns:
            True 成功过期，False 未找到或已过期。
        """
        now = datetime.now(tz=UTC)
        async with _get_session() as session, session.begin():
            result = await session.execute(
                update(HealthFact)
                .where(
                    and_(
                        HealthFact.id == fact_id,
                        HealthFact.user_id == self.user_id,
                        HealthFact.valid_until.is_(None),
                    )
                )
                .values(valid_until=now)
            )
            updated = result.rowcount > 0  # type: ignore[attr-defined]
            if updated:
                logger.debug("fact.invalidate id=%s user=%s", fact_id, self.user_id)
                await FactCache.invalidate_user(self.user_id)
            return bool(updated)

    async def invalidate_by_subject(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> int:
        """
        批量过期指定 subject（可选 predicate）下的所有当前有效记录。

        用途：用户康复后 invalidate 全部伤病记录；
             用户切换运动目标时 invalidate 所有旧目标。

        Returns:
            被过期的记录数量。
        """
        now = datetime.now(tz=UTC)
        conditions = [
            HealthFact.user_id == self.user_id,
            HealthFact.subject == subject,
            HealthFact.valid_until.is_(None),
        ]
        if predicate is not None:
            conditions.append(HealthFact.predicate == predicate)

        async with _get_session() as session, session.begin():
            result = await session.execute(
                update(HealthFact)
                .where(and_(*conditions))
                .values(valid_until=now)
            )
            count = result.rowcount  # type: ignore[attr-defined]
            logger.debug(
                "fact.invalidate_by_subject user=%s subject=%s predicate=%s count=%d",
                self.user_id, subject, predicate, count,
            )
            await FactCache.invalidate_user(self.user_id)
            return int(count) if count is not None else 0

    # ── 查询 ─────────────────────────────────────────────────────────────────

    async def query_current(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> list[HealthFact]:
        """
        查询当前有效事实（valid_until IS NULL）。

        最常用的查询入口：获取用户当前的目标、限制、基线等。
        命中缓存时直接返回（降低 DB 查询压力）。
        """
        # Check cache first
        if predicate is None:
            cached = await FactCache.get(self.user_id, subject, "all")
            if cached is not None:
                return [HealthFact(**r) for r in cached]
        else:
            cached = await FactCache.get(self.user_id, subject, predicate)
            if cached is not None:
                return [HealthFact(**cached)]

        conditions = [
            HealthFact.user_id == self.user_id,
            HealthFact.subject == subject,
            HealthFact.valid_until.is_(None),
        ]
        if predicate is not None:
            conditions.append(HealthFact.predicate == predicate)

        async with _get_session() as session:
            result = await session.execute(
                select(HealthFact)
                .where(and_(*conditions))
                .order_by(HealthFact.valid_from.desc())
            )
            facts = list(result.scalars().all())

        # Cache results
        if facts:
            if predicate is None:
                await FactCache.set(
                    self.user_id, subject, "all",
                    {"items": [
                        {"id": f.id, "subject": f.subject, "predicate": f.predicate,
                         "object_json": f.object_json} for f in facts
                    ]},
                )
            else:
                f = facts[0]
                await FactCache.set(
                    self.user_id, subject, predicate,
                    {"id": f.id, "subject": f.subject, "predicate": f.predicate,
                     "object_json": f.object_json},
                )

        return facts

    async def query_history(
        self,
        subject: str,
        predicate: str | None = None,
        limit: int = 50,
    ) -> list[HealthFact]:
        """
        查询历史记录（含已过期），按 valid_from 倒序。

        用于展示用户训练目标变更历程、伤病历史等。
        """
        conditions = [
            HealthFact.user_id == self.user_id,
            HealthFact.subject == subject,
        ]
        if predicate is not None:
            conditions.append(HealthFact.predicate == predicate)

        async with _get_session() as session:
            result = await session.execute(
                select(HealthFact)
                .where(and_(*conditions))
                .order_by(HealthFact.valid_from.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_all_current(self) -> list[HealthFact]:
        """
        获取该用户所有当前有效事实（供 MCP rhythmind_status 工具使用）。
        """
        async with _get_session() as session:
            result = await session.execute(
                select(HealthFact)
                .where(
                    and_(
                        HealthFact.user_id == self.user_id,
                        HealthFact.valid_until.is_(None),
                    )
                )
                .order_by(HealthFact.subject, HealthFact.predicate)
            )
            return list(result.scalars().all())

    async def get_fact_by_id(self, fact_id: int) -> HealthFact | None:
        """按 ID 获取单条事实（含已过期）。"""
        async with _get_session() as session:
            result = await session.execute(
                select(HealthFact).where(
                    and_(
                        HealthFact.id == fact_id,
                        HealthFact.user_id == self.user_id,
                    )
                )
            )
            return result.scalar_one_or_none()

    # ── 便捷方法（Agent 内联调用）────────────────────────────────────────────

    async def get_current_goal(self) -> dict[str, Any] | None:
        """快捷：获取用户当前训练目标。"""
        facts = await self.query_current("user_goal", "targets")
        return facts[0].object_json if facts else None

    async def get_current_injuries(self) -> list[dict[str, Any]]:
        """快捷：获取用户当前所有伤病限制。"""
        facts = await self.query_current("injury", "restricts")
        return [f.object_json for f in facts]

    async def set_goal(
        self, goal: str, detail: dict[str, Any] | None = None, source: str = "user"
    ) -> HealthFact:
        """快捷：设置训练目标（自动 invalidate 旧目标）。"""
        obj = {"goal": goal, **(detail or {})}
        return await self.write_fact("user_goal", "targets", obj, source=source)

    async def add_injury(
        self, area: str, restriction: str, source: str = "user"
    ) -> HealthFact:
        """快捷：追加伤病记录（不 invalidate 其他伤病）。"""
        return await self.write_fact_additive(
            "injury", "restricts",
            {"area": area, "restriction": restriction},
            source=source,
        )

    async def recover_from_injury(self, area: str | None = None) -> int:
        """快捷：标记伤病康复（invalidate 伤病记录）。"""
        if area:
            # 只过期特定部位（需逐条检查 object_json）
            facts = await self.query_current("injury", "restricts")
            count = 0
            for f in facts:
                if f.object_json.get("area") == area:
                    await self.invalidate_fact(f.id)
                    count += 1
            return count
        else:
            # 全部康复
            return await self.invalidate_by_subject("injury", "restricts")
