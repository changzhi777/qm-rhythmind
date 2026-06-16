# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Admin skill-approval integration tests (R-4)
# ─────────────────────────────────────────────────────────────────────────────
"""
Closes THREAT_MODEL.md R-4 (skill / QMD poisoning) on the code side.

Coverage:
  1. Non-admin user cannot list pending nor approve/reject (403)
  2. Admin can list pending skills
  3. Approve flow: status flips to 'approved' + audit event emitted
  4. Reject flow: status flips to 'rejected' + audit event emitted
  5. Approve of unknown hash → 404
  6. SkillEngine with require_approval=True writes pending; once approved by admin,
     SELECT WHERE status='approved' returns the skill
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ── Helpers ─────────────────────────────────────────────────────────────────

async def _seed_skill(agent: str, skill_hash: str, status: str = "pending") -> int:
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import SkillRecord

    async with AsyncSessionLocal() as sess:
        rec = SkillRecord(
            agent=agent, skill_hash=skill_hash,
            content=f"## skill {skill_hash}\n", source_task="test",
            confidence=0.9, status=status,
        )
        sess.add(rec)
        await sess.commit()
        return rec.id


# ── 1. Non-admin → 403 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_admin_cannot_list_pending(app_client, patched_redis, monkeypatch):
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    # bob is not admin
    resp = await app_client.get(
        "/api/v1/admin/skills/pending",
        headers={"Authorization": "Bearer bob"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_approve(app_client, patched_redis, monkeypatch):
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("metrics_agent", "h_nonadmin")

    resp = await app_client.post(
        "/api/v1/admin/skills/h_nonadmin/approve",
        headers={"Authorization": "Bearer bob"},
    )
    assert resp.status_code == 403


# ── 2. Admin lists pending ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_lists_pending_skills(app_client, patched_redis, monkeypatch):
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("metrics_agent", "h_001", status="pending")
    await _seed_skill("data_agent", "h_002", status="pending")
    await _seed_skill("coach_agent", "h_003", status="approved")  # 不应出现在 pending

    resp = await app_client.get(
        "/api/v1/admin/skills/pending",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    hashes = {item["skill_hash"] for item in body["items"]}
    assert hashes == {"h_001", "h_002"}
    assert body["total"] == 2


# ── 3. Approve flow ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_approves_skill_updates_status_and_audit(
    app_client, patched_redis, monkeypatch,
):
    from sqlalchemy import select

    from rhythmind.audit import AuditEvent, InMemorySink, get_sink, install_audit_sink
    from rhythmind.config import settings
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import SkillRecord

    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("metrics_agent", "h_approve")

    prev = get_sink()
    sink = InMemorySink()
    install_audit_sink(sink)
    try:
        resp = await app_client.post(
            "/api/v1/admin/skills/h_approve/approve",
            headers={"Authorization": "Bearer alice"},
        )
        assert resp.status_code == 204, resp.text
    finally:
        install_audit_sink(prev)

    async with AsyncSessionLocal() as sess:
        row = (await sess.execute(
            select(SkillRecord).where(SkillRecord.skill_hash == "h_approve")
        )).scalar_one()
    assert row.status == "approved"

    # Audit event emitted
    rs = sink.find(AuditEvent.SKILL_APPROVED)
    assert len(rs) == 1
    assert rs[0].user_id == "alice"
    assert rs[0].fields.get("skill_hash") == "h_approve"


# ── 4. Reject flow ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_rejects_skill_updates_status_and_audit(
    app_client, patched_redis, monkeypatch,
):
    from sqlalchemy import select

    from rhythmind.audit import AuditEvent, InMemorySink, get_sink, install_audit_sink
    from rhythmind.config import settings
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import SkillRecord

    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("metrics_agent", "h_reject")

    prev = get_sink()
    sink = InMemorySink()
    install_audit_sink(sink)
    try:
        resp = await app_client.post(
            "/api/v1/admin/skills/h_reject/reject",
            headers={"Authorization": "Bearer alice"},
        )
        assert resp.status_code == 204, resp.text
    finally:
        install_audit_sink(prev)

    async with AsyncSessionLocal() as sess:
        row = (await sess.execute(
            select(SkillRecord).where(SkillRecord.skill_hash == "h_reject")
        )).scalar_one()
    assert row.status == "rejected"

    rs = sink.find(AuditEvent.SKILL_REJECTED)
    assert len(rs) == 1
    assert rs[0].fields.get("skill_hash") == "h_reject"


# ── 5. Unknown hash → 404 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approve_unknown_hash_404(app_client, patched_redis, monkeypatch):
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    resp = await app_client.post(
        "/api/v1/admin/skills/does_not_exist/approve",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_unknown_hash_404(app_client, patched_redis, monkeypatch):
    """拒绝不存在的 skill 应返回 404。"""
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    resp = await app_client.post(
        "/api/v1/admin/skills/does_not_exist/reject",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_already_approved_is_idempotent(app_client, patched_redis, monkeypatch):  # noqa: E501
    """已 approved 的 skill 再次 approve 应幂等成功（不报错）。"""
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("data_agent", "h_already_approved", status="approved")

    # 再次 approve
    resp = await app_client.post(
        "/api/v1/admin/skills/h_already_approved/approve",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_list_pending_respects_pagination(app_client, patched_redis, monkeypatch):
    """pending 列表应支持 limit 和 offset。"""
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")

    # 创建 5 个 pending skills
    for i in range(5):
        await _seed_skill("coach_agent", f"h_page_{i}", status="pending")

    # limit=2
    resp = await app_client.get(
        "/api/v1/admin/skills/pending",
        headers={"Authorization": "Bearer alice"},
        params={"limit": 2},
    )
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5  # total 不受 limit 影响


@pytest.mark.asyncio
async def test_list_pending_respects_offset(app_client, patched_redis, monkeypatch):
    """pending 列表 offset 应跳过前 N 条。"""
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")

    for i in range(5):
        await _seed_skill("coach_agent", f"h_offset_{i}", status="pending")

    # offset=3
    resp = await app_client.get(
        "/api/v1/admin/skills/pending",
        headers={"Authorization": "Bearer alice"},
        params={"offset": 3},
    )
    body = resp.json()
    assert len(body["items"]) == 2  # 5 - 3 = 2


@pytest.mark.asyncio
async def test_reject_does_not_push_to_qmd(app_client, patched_redis, monkeypatch):
    """拒绝的 skill 不应推送到 QMD。"""
    from rhythmind.config import settings
    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    await _seed_skill("metrics_agent", "h_no_qmd", status="pending")

    # 用 mock QMD 验证不会调用 index_skill
    with patch("rhythmind.api.routers.admin.QMDClient") as mock_qmd_class:
        mock_qmd = AsyncMock()
        mock_qmd_class.return_value = mock_qmd

        resp = await app_client.post(
            "/api/v1/admin/skills/h_no_qmd/reject",
            headers={"Authorization": "Bearer alice"},
        )
        assert resp.status_code == 204

        # QMD 不应被调用（因为 reject 不推送）
        mock_qmd.index_skill.assert_not_called()


# ── 6. SkillEngine require_approval flow end-to-end ────────────────────────

@pytest.mark.asyncio
async def test_skill_engine_writes_pending_when_require_approval(
    app_client, patched_redis, monkeypatch,
):
    """
    With skill_require_approval=True, SkillEngine.persist_to_qmd() writes
    rows with status='pending'. After admin approval, the row flips and
    a query for status='approved' returns the skill.
    """
    from sqlalchemy import select

    from rhythmind.config import settings
    from rhythmind.core.memory.manager import AsyncSessionLocal
    from rhythmind.core.memory.models import SkillRecord
    from rhythmind.core.skill.engine import SkillEngine

    monkeypatch.setattr(settings, "admin_user_ids", "alice")
    monkeypatch.setattr(settings, "skill_require_approval", True)

    # Avoid real QMD HTTP — engine swallows exceptions but we don't even want that
    # noise; mock the QMDClient.index_skill to a no-op.
    from rhythmind.core.qmd.client import QMDClient
    async def _noop(*a, **kw): return None
    monkeypatch.setattr(QMDClient, "index_skill", _noop, raising=False)

    engine = SkillEngine(agent="test_agent", qmd_client=QMDClient())
    skills = [{
        "id": "test_agent_abc12345",
        "agent": "test_agent",
        "content": "## skill test\n",
        "task_type": "demo",
    }]
    await engine.persist_to_qmd(skills)

    # The new row should be 'pending'
    async with AsyncSessionLocal() as sess:
        row = (await sess.execute(
            select(SkillRecord).where(SkillRecord.skill_hash == "abc12345")
        )).scalar_one()
    assert row.status == "pending"

    # Admin approves
    resp = await app_client.post(
        "/api/v1/admin/skills/abc12345/approve",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 204

    # Now status='approved' filter should find it
    async with AsyncSessionLocal() as sess:
        approved = (await sess.execute(
            select(SkillRecord).where(SkillRecord.status == "approved")
        )).scalars().all()
    assert any(r.skill_hash == "abc12345" for r in approved)
