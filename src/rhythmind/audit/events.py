"""
audit/events.py — 事件类型常量。

新增事件需要：
  1. 在这里添加常量
  2. 在 docs/SECURITY.md §6 与 docs/THREAT_MODEL.md §3.1 R 行更新文档
"""
from __future__ import annotations


class AuditEvent:
    """事件类型字符串。值会写到 sink 的 `event` 字段。"""

    # ── 用户数据主体权利 ────────────────────────────────────────────────
    PRIVACY_EXPORT          = "privacy.export"
    PRIVACY_DELETE          = "privacy.delete"
    PRIVACY_DELETE_FAILURE  = "privacy.delete_failure"

    # ── 鉴权 / 安全门 ──────────────────────────────────────────────────
    AUTH_BYPASS_USED        = "auth.bypass_used"
    MCP_UNAUTHENTICATED     = "mcp.unauthenticated"
    CONFIG_UNSAFE_STARTUP   = "config.unsafe_startup"

    # ── 业务限流 ──────────────────────────────────────────────────────
    RATE_LIMIT_BLOCKED      = "rate_limit.blocked"

    # ── 模型 spec 切换（运行时改 MODEL_PRIMARY_SPEC 等）──────────────
    MODEL_SPEC_CHANGED      = "model.spec_changed"

    # ── Skill 审核（v0.1.6+ R-4）────────────────────────────────────
    SKILL_APPROVED          = "skill.approved"
    SKILL_REJECTED          = "skill.rejected"
