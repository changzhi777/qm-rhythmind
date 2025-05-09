# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/skill/engine.py — SkillEngine

协调 SkillExtractor + DB 持久化 + QMD 同步三步流程。

调用链：
  HermesBase.run()
    → skill.extract(ctx, compliance_result)
    → skill.persist_to_qmd(extracted_skills)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from rhythmind.config import settings
from rhythmind.core.memory.models import SkillRecord
from rhythmind.core.memory.manager import AsyncSessionLocal, _build_upsert
from rhythmind.core.qmd.client import QMDClient

from .extractor import SkillExtractor

logger = logging.getLogger(__name__)


class SkillEngine:
    """
    单个 Agent 的技能引擎。

    agent: Agent 名称，用于隔离技能归属。
    """

    def __init__(self, agent: str, qmd_client: QMDClient | None = None) -> None:
        self.agent = agent
        self._extractor = SkillExtractor()
        self._qmd = qmd_client or QMDClient()

    async def extract(
        self,
        task_type: str,
        skill_candidates: list[str],
        output: Any,
        confidence: float,
    ) -> list[dict[str, str]]:
        """
        提取技能候选列表。

        封装 SkillExtractor.extract()，对外接口更简洁。
        """
        return self._extractor.extract(
            task_type=task_type,
            skill_candidates=skill_candidates,
            output=output,
            confidence=confidence,
            agent=self.agent,
        )

    async def persist_to_qmd(
        self,
        skills: list[dict[str, str]],
    ) -> None:
        """
        将提取到的技能条目同步到 DB + QMD。

        两步写入：
          1. 写 SkillRecord 表（持久化，可离线查询）
          2. upsert 到 QMD agent_skills collection（语义检索）
        """
        if not skills:
            return

        async with AsyncSessionLocal() as session:
            async with session.begin():
                for skill in skills:
                    await self._upsert_db(session, skill)

        # QMD 写入（独立 try，失败不影响主流程）
        for skill in skills:
            try:
                await self._qmd.index_skill(
                    agent=skill["agent"],
                    skill_content=skill["content"],
                    task_type=skill.get("task_type", ""),
                )
            except Exception as e:
                logger.warning("skill.persist_to_qmd qmd_error=%s id=%s", e, skill["id"])

        logger.info(
            "skill.persist agent=%s count=%d", self.agent, len(skills)
        )

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _upsert_db(
        session: AsyncSession,
        skill: dict[str, str],
    ) -> None:
        skill_hash = skill["id"].split("_")[-1]
        is_sqlite = "sqlite" in settings.database_url
        insert = _build_upsert(is_sqlite)
        stmt = insert(SkillRecord).values(
            agent=skill["agent"],
            skill_hash=skill_hash,
            content=skill["content"],
            source_task=skill.get("task_type", ""),
            confidence=0.85,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["agent", "skill_hash"],
            set_={"use_count": SkillRecord.use_count + 1},
        )
        await session.execute(stmt)
