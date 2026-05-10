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
import rhythmind.core.memory.manager as _mem_mgr  # 通过模块引用访问 AsyncSessionLocal，
                                                   # 兼容 conftest.reset_db 的运行时替换
from rhythmind.core.memory.manager import _build_upsert
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
          1. 写 SkillRecord 表，status 由 settings.skill_require_approval 决定
             - True  → status='pending'，等 admin approve
             - False → status='approved'，立即可被 QMD 检索
          2. 仅当 status='approved' 时才推到 QMD agent_skills collection
        """
        if not skills:
            return

        # 默认视为 approved；require_approval 时新写入进 pending
        new_status = "pending" if settings.skill_require_approval else "approved"

        async with _mem_mgr.AsyncSessionLocal() as session:
            async with session.begin():
                for skill in skills:
                    await self._upsert_db(session, skill, new_status)

        # QMD 写入（独立 try，失败不影响主流程）
        # 仅在 approved 路径推 QMD；pending skill 不参与检索
        if new_status == "approved":
            for skill in skills:
                try:
                    await self._qmd.index_skill(
                        agent=skill["agent"],
                        skill_content=skill["content"],
                        task_type=skill.get("task_type", ""),
                    )
                except Exception as e:
                    logger.warning(
                        "skill.persist_to_qmd qmd_error=%s id=%s", e, skill["id"]
                    )
        else:
            logger.info(
                "skill.persist agent=%s count=%d status=pending qmd_skipped",
                self.agent, len(skills),
            )

        logger.info(
            "skill.persist agent=%s count=%d status=%s",
            self.agent, len(skills), new_status,
        )

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _upsert_db(
        session: AsyncSession,
        skill: dict[str, str],
        new_status: str = "approved",
    ) -> None:
        """
        向 SkillRecord 表 upsert 一条记录。

        冲突时（同 agent+hash）只递增 use_count，**不覆盖 status**——
        避免管理员 reject 之后下次自动提取又被重置为 pending/approved。
        """
        skill_hash = skill["id"].split("_")[-1]
        is_sqlite = "sqlite" in settings.database_url
        insert = _build_upsert(is_sqlite)
        stmt = insert(SkillRecord).values(
            agent=skill["agent"],
            skill_hash=skill_hash,
            content=skill["content"],
            source_task=skill.get("task_type", ""),
            confidence=0.85,
            status=new_status,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["agent", "skill_hash"],
            # 注意：仅更新 use_count，不动 status / content
            set_={"use_count": SkillRecord.use_count + 1},
        )
        await session.execute(stmt)
