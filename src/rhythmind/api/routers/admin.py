# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Admin router (skill review for R-4)
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/admin.py — 管理接口（v0.1.6+）

当前覆盖的能力：Skill 审核（关闭 THREAT_MODEL.md R-4 的代码侧依赖）。

Endpoints:
  GET  /admin/skills/pending        — 列出 status='pending' 的 skill
  POST /admin/skills/{hash}/approve — 标记为 approved 并推 QMD
  POST /admin/skills/{hash}/reject  — 标记为 rejected（不推 QMD，不再使用）

鉴权:
  额外要求当前 user_id 在 settings.admin_user_ids_set 中；否则 403。
  与 CurrentUserId 依赖叠加，确保 admin 同时持有合法 token。
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update

from rhythmind.api.deps import CurrentUserId
from rhythmind.audit import AuditEvent, audit_log
from rhythmind.config import settings
from rhythmind.core.memory.models import SkillRecord
from rhythmind.core.qmd import QMDClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ── admin 角色门 ────────────────────────────────────────────────────────────

async def require_admin(user_id: CurrentUserId) -> str:
    """要求 user_id ∈ settings.admin_user_ids_set；否则 403。"""
    admins = settings.admin_user_ids_set
    if not admins or user_id not in admins:
        # 不暴露白名单成员；返回固定 403
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user_id


AdminUserId = Annotated[str, Depends(require_admin)]


# ── /admin/skills/pending ───────────────────────────────────────────────────

@router.get(
    "/skills/pending",
    summary="列出待审核的 skill",
)
async def list_pending_skills(
    admin_id: AdminUserId,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """
    返回 status='pending' 的 skill 记录，按 created_at 降序。
    """
    # 懒导入 sessionmaker：兼容 conftest.reset_db 的运行时替换
    import rhythmind.core.memory.manager as _mem_mgr

    async with _mem_mgr.AsyncSessionLocal() as sess:
        stmt = (
            select(SkillRecord)
            .where(SkillRecord.status == "pending")
            .order_by(SkillRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await sess.execute(stmt)).scalars().all()

    return {
        "total": len(rows),
        "items": [
            {
                "id":          r.id,
                "agent":       r.agent,
                "skill_hash":  r.skill_hash,
                "content":     r.content,
                "source_task": r.source_task,
                "confidence":  r.confidence,
                "created_at":  r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


# ── /admin/skills/{hash}/approve ────────────────────────────────────────────

@router.post(
    "/skills/{skill_hash}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="批准 skill 并推到 QMD",
)
async def approve_skill(
    skill_hash: str,
    admin_id: AdminUserId,
) -> None:
    """
    把 skill 状态置为 approved，并把内容推到 QMD agent_skills collection。
    若 skill 不存在 → 404；若已是 approved → 视为幂等成功。
    """
    import rhythmind.core.memory.manager as _mem_mgr

    async with _mem_mgr.AsyncSessionLocal() as sess:
        row = (await sess.execute(
            select(SkillRecord).where(SkillRecord.skill_hash == skill_hash)
        )).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail="skill not found")

        if row.status != "approved":
            await sess.execute(
                update(SkillRecord)
                .where(SkillRecord.id == row.id)
                .values(status="approved")
            )
            await sess.commit()

        agent = row.agent
        content = row.content
        source_task = row.source_task

    # 推 QMD（独立 try，失败不阻塞 approve 结果）
    try:
        qmd = QMDClient()
        await qmd.index_skill(agent=agent, skill_content=content, task_type=source_task)
    except Exception as exc:
        logger.warning("admin.approve qmd_error=%s hash=%s", exc, skill_hash)

    audit_log(
        AuditEvent.SKILL_APPROVED,
        user_id=admin_id,
        skill_hash=skill_hash,
        agent=agent,
    )
    logger.info("admin.skill_approved hash=%s by=%s", skill_hash, admin_id)


# ── /admin/skills/{hash}/reject ─────────────────────────────────────────────

@router.post(
    "/skills/{skill_hash}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="拒绝 skill（不推 QMD，不再使用）",
)
async def reject_skill(
    skill_hash: str,
    admin_id: AdminUserId,
) -> None:
    import rhythmind.core.memory.manager as _mem_mgr

    async with _mem_mgr.AsyncSessionLocal() as sess:
        row = (await sess.execute(
            select(SkillRecord).where(SkillRecord.skill_hash == skill_hash)
        )).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail="skill not found")

        await sess.execute(
            update(SkillRecord)
            .where(SkillRecord.id == row.id)
            .values(status="rejected")
        )
        await sess.commit()
        agent = row.agent

    audit_log(
        AuditEvent.SKILL_REJECTED,
        user_id=admin_id,
        skill_hash=skill_hash,
        agent=agent,
    )
    logger.info("admin.skill_rejected hash=%s by=%s", skill_hash, admin_id)
