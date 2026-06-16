# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND — Audit log integration tests (R-3 in THREAT_MODEL.md)
# ─────────────────────────────────────────────────────────────────────────────
"""
Verifies that the four security-critical paths each emit an audit record:

  1. /privacy/export                  → AuditEvent.PRIVACY_EXPORT
  2. /privacy/delete (clean)          → AuditEvent.PRIVACY_DELETE
  3. dev_auth_bypass usage            → AuditEvent.AUTH_BYPASS_USED
  4. mcp_require_auth=False access    → AuditEvent.MCP_UNAUTHENTICATED

Plus value-clipping (PII guard) and the InMemorySink contract.
"""
from __future__ import annotations

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def memsink():
    """Install an InMemorySink for the duration of one test, then restore."""
    from rhythmind.audit import InMemorySink, get_sink, install_audit_sink
    prev = get_sink()
    sink = InMemorySink()
    install_audit_sink(sink)
    try:
        yield sink
    finally:
        install_audit_sink(prev)


# ── 1. Privacy export emits ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_privacy_export_emits_audit(app_client, patched_redis, memsink):
    from rhythmind.audit import AuditEvent

    resp = await app_client.get(
        "/api/v1/privacy/export",
        headers={"Authorization": "Bearer alice"},
    )
    assert resp.status_code == 200

    rs = memsink.find(AuditEvent.PRIVACY_EXPORT)
    assert len(rs) == 1
    rec = rs[0]
    assert rec.user_id == "alice"
    assert "bytes" in rec.fields
    assert rec.fields["memory_rows"] == 0   # 没种数据时为 0
    assert rec.fields["facts_rows"] == 0


# ── 2. Privacy delete emits clean event ────────────────────────────────────

@pytest.mark.asyncio
async def test_privacy_delete_emits_audit(app_client, patched_redis, memsink):
    from rhythmind.audit import AuditEvent

    resp = await app_client.post(
        "/api/v1/privacy/delete",
        headers={"Authorization": "Bearer alice"},
        json={"confirm_token": "alice"},
    )
    assert resp.status_code == 200

    # 没接 InfluxDB / 真 QMD，failures>0 是预期；判别用 PRIVACY_DELETE_FAILURE
    rs = memsink.records
    assert any(r.event in (
        AuditEvent.PRIVACY_DELETE,
        AuditEvent.PRIVACY_DELETE_FAILURE,
    ) for r in rs), [r.event for r in rs]
    rec = next(r for r in rs if r.event in (
        AuditEvent.PRIVACY_DELETE, AuditEvent.PRIVACY_DELETE_FAILURE,
    ))
    assert rec.user_id == "alice"
    assert "successes" in rec.fields and "failures" in rec.fields


# ── 3. dev_auth_bypass usage is audited ────────────────────────────────────

@pytest.mark.asyncio
async def test_dev_auth_bypass_audited(app_client, patched_redis, memsink):
    from rhythmind.audit import AuditEvent

    # /privacy/export 是 authenticated 路由，会触发 deps.py 的 dev_auth_bypass 路径。
    # （/privacy/policy 是 public，不会过 CurrentUserId 依赖。）
    resp = await app_client.get(
        "/api/v1/privacy/export",
        headers={"Authorization": "Bearer some_user"},
    )
    assert resp.status_code == 200, resp.text

    rs = memsink.find(AuditEvent.AUTH_BYPASS_USED)
    assert len(rs) >= 1, [(r.event, r.user_id) for r in memsink.records]
    assert any(r.user_id == "some_user" for r in rs)


# ── 4. MCP unauth path is audited (only when flag flipped) ─────────────────

@pytest.mark.asyncio
async def test_mcp_unauth_emits_when_flag_off(app_client, patched_redis, memsink, monkeypatch):  # noqa: E501
    from rhythmind.audit import AuditEvent
    from rhythmind.config import settings

    # 在测试中临时关闭 MCP 鉴权（注意：仅在 ENV != prod 才合法；conftest 用 dev）
    monkeypatch.setattr(settings, "mcp_require_auth", False)

    await app_client.post("/mcp/messages/?session_id=fake", json={})

    rs = memsink.find(AuditEvent.MCP_UNAUTHENTICATED)
    assert len(rs) >= 1
    assert rs[0].fields.get("path") == "/mcp/messages/"


# ── 5. Sink swap & default behavior ────────────────────────────────────────

def test_install_audit_sink_swaps():
    from rhythmind.audit import (
        AuditEvent,
        InMemorySink,
        audit_log,
        get_sink,
        install_audit_sink,
    )
    prev = get_sink()
    a = InMemorySink()
    b = InMemorySink()
    try:
        install_audit_sink(a)
        audit_log(AuditEvent.PRIVACY_EXPORT, user_id="x", bytes=1)
        install_audit_sink(b)
        audit_log(AuditEvent.PRIVACY_EXPORT, user_id="y", bytes=1)
        assert len(a.records) == 1 and a.records[0].user_id == "x"
        assert len(b.records) == 1 and b.records[0].user_id == "y"
    finally:
        install_audit_sink(prev)


# ── 6. Long string fields are clipped (PII guard) ──────────────────────────

def test_audit_log_clips_long_strings():
    from rhythmind.audit import (
        AuditEvent,
        InMemorySink,
        audit_log,
        get_sink,
        install_audit_sink,
    )
    prev = get_sink()
    sink = InMemorySink()
    install_audit_sink(sink)
    try:
        huge = "x" * 5000
        audit_log(AuditEvent.PRIVACY_EXPORT, user_id="alice", note=huge)
        rec = sink.records[0]
        clipped = rec.fields["note"]
        # 必须截短到 _MAX_VALUE_CHARS (512) + "...<truncated N>" 后缀
        assert len(clipped) < 1000
        assert "truncated" in clipped
        assert clipped.startswith("x" * 512)
    finally:
        install_audit_sink(prev)


# ── 7. audit_log is exception-safe ─────────────────────────────────────────

def test_audit_log_swallows_sink_errors(monkeypatch):
    from rhythmind.audit import (
        AuditEvent,
        AuditSink,
        audit_log,
        get_sink,
        install_audit_sink,
    )

    class _BoomSink(AuditSink):
        def emit(self, record):
            raise RuntimeError("disk full")

    prev = get_sink()
    install_audit_sink(_BoomSink())
    try:
        # Must not raise — production paths can't fail because audit failed.
        audit_log(AuditEvent.PRIVACY_EXPORT, user_id="alice")
    finally:
        install_audit_sink(prev)
