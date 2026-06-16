"""
migration: 004_audit_session_tables

Revision ID: 004_audit_session_tables
Revises: 003_skill_status
Create Date: 2026-05-13

新增表：
  - audit_log      ：运营审计日志（防篡改，PG 持久化）
  - user_session   ：用户会话表（Redis session 的 PG 备份，支持审计追溯）

索引策略：
  - audit_log(user_id, created_at)     — 按用户查审计历史
  - audit_log(event, created_at)       — 按事件类型聚合
  - audit_log(created_at)              — 时序清理（按时间删除旧日志）
  - user_session(user_id, created_at)  — 用户会话历史
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_audit_session_tables"
down_revision: str | None = "003_skill_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── audit_log ──────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.String(64), nullable=False, server_default="''"),
        sa.Column("event", sa.String(64), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),  # noqa: E501
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            index=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_user_created",
        "audit_log",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_event_created",
        "audit_log",
        ["event", "created_at"],
    )

    # ── user_session ──────────────────────────────────────────────────
    op.create_table(
        "user_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("intents_used", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),  # noqa: E501
        sa.Column("outcome", sa.String(32), nullable=False, server_default="'success'"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "ended_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_session_user_created",
        "user_session",
        ["user_id", "created_at"],
    )

    # ── 自动更新 updated_at 触发器（PostgreSQL）──────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)


def downgrade() -> None:
    op.drop_table("user_session")
    op.drop_table("audit_log")