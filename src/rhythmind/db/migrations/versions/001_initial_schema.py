"""初始数据库 Schema

Revision ID: 001_initial
Revises:
Create Date: 2026-05-08

建表：
  - agent_memory  （核心记忆表，JSONB 存储）
  - skill_record  （技能记录表）

索引策略：
  - (namespace, key) UNIQUE — upsert 锚点
  - (user_id, agent)        — 最高频查询路径
  - value_json GIN          — JSONB 内容过滤（Phase 2 用）
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── agent_memory ────────────────────────────────────────────────────
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("namespace", sa.String(256), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_json", JSONB(none_as_null=True), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tags", JSONB(none_as_null=True), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("mem_type", sa.String(32), nullable=False, server_default="'project'"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # 唯一索引（upsert 锚点）
    op.create_index(
        "ix_memory_ns_key", "agent_memory", ["namespace", "key"], unique=True
    )
    # 查询索引
    op.create_index(
        "ix_memory_user_agent", "agent_memory", ["user_id", "agent"], unique=False
    )
    # GIN 索引：JSONB 内容过滤
    op.create_index(
        "ix_memory_value_gin",
        "agent_memory",
        ["value_json"],
        postgresql_using="gin",
    )

    # ── skill_record ─────────────────────────────────────────────────────
    op.create_table(
        "skill_record",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent", sa.String(64), nullable=False),
        sa.Column("skill_hash", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_task", sa.String(128), nullable=False, server_default="''"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("synced_to_qmd", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_agent_hash", "skill_record", ["agent", "skill_hash"], unique=True
    )
    op.create_index(
        "ix_skill_agent", "skill_record", ["agent"], unique=False
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
    op.execute("""
        CREATE TRIGGER trg_agent_memory_updated_at
        BEFORE UPDATE ON agent_memory
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agent_memory_updated_at ON agent_memory")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column")
    op.drop_table("skill_record")
    op.drop_table("agent_memory")
