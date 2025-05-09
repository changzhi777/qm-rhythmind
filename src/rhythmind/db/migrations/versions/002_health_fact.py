"""新增 health_fact 时序知识图谱表

Revision ID: 002_health_fact
Revises: 001_initial
Create Date: 2026-05-08

建表：
  health_fact — 健康时序知识图谱（参考 MemPalace KG 模式）

Schema 设计要点：
  - (subject, predicate, valid_until IS NULL) 确保最多一条当前有效记录
  - valid_until NULL  → 当前有效
  - valid_until 非空  → 已过期（保留历史，不物理删除）
  - object_json JSONB → 支持任意结构的事实值
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002_health_fact"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_fact",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        # 三元组
        sa.Column("subject", sa.String(128), nullable=False),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column(
            "object_json",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
        # 溯源
        sa.Column("source", sa.String(64), nullable=False, server_default="'system'"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        # 时序窗口
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 高频查询路径：按 user + subject + predicate 筛当前有效记录
    op.create_index(
        "ix_fact_user_subject",
        "health_fact",
        ["user_id", "subject", "predicate"],
    )
    # 历史回溯：按 user + valid_from 排序
    op.create_index(
        "ix_fact_user_valid_from",
        "health_fact",
        ["user_id", "valid_from"],
    )
    # GIN 索引：object_json 内容过滤（Phase 2 用，如 @> '{"goal": "马拉松"}'）
    op.create_index(
        "ix_fact_object_gin",
        "health_fact",
        ["object_json"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_fact_object_gin", table_name="health_fact")
    op.drop_index("ix_fact_user_valid_from", table_name="health_fact")
    op.drop_index("ix_fact_user_subject", table_name="health_fact")
    op.drop_table("health_fact")
