"""知识库表

Revision ID: 006_knowledge_tables
Revises: 005_medical_tables
Create Date: 2026-05-27

新增 2 张知识库表：
  - knowledge_article    领域知识条目（结构化文章/摘要）
  - knowledge_reference  文献引用（学术/临床指南/权威来源）
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006_knowledge_tables"
down_revision: str | None = "005_medical_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── knowledge_article ─────────────────────────────────────────────
    op.create_table(
        "knowledge_article",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("domain", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.String(2048), nullable=False, server_default=""),
        sa.Column(
            "content",
            JSONB(none_as_null=True),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(512), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="'web'"),
        sa.Column("source_url", sa.String(1024), nullable=True),
        sa.Column("published_date", sa.String(32), nullable=True),
        sa.Column(
            "tags",
            JSONB(none_as_null=True),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("relevance_score", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ka_domain", "knowledge_article", ["domain"])
    op.create_index("ix_ka_source_type", "knowledge_article", ["source_type"])

    # ── knowledge_reference ────────────────────────────────────────────
    op.create_table(
        "knowledge_reference",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_article.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref_type", sa.String(32), nullable=False, server_default="'citation'"),
        sa.Column("ref_title", sa.String(512), nullable=False),
        sa.Column("ref_url", sa.String(1024), nullable=True),
        sa.Column("ref_authors", sa.String(1024), nullable=True),
        sa.Column("ref_year", sa.Integer(), nullable=True),
        sa.Column("ref_journal", sa.String(256), nullable=True),
        sa.Column("ref_doi", sa.String(256), nullable=True),
        sa.Column(
            "key_findings",
            JSONB(none_as_null=True),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kr_article_id", "knowledge_reference", ["article_id"])
    op.create_index("ix_kr_ref_type", "knowledge_reference", ["ref_type"])


def downgrade() -> None:
    op.drop_table("knowledge_reference")
    op.drop_table("knowledge_article")
