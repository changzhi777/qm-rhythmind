"""skill_record 增加 status 列（审核状态）

Revision ID: 003_skill_status
Revises: 002_health_fact
Create Date: 2026-05-09

变更:
  - skill_record 表增加 status VARCHAR(16) NOT NULL DEFAULT 'approved'
  - 新增 ix_skill_status 索引

向后兼容:
  默认值 'approved' 让所有现有 skill 视为已审核，
  新写入由 SkillEngine 根据 settings.skill_require_approval 决定。
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_skill_status"
down_revision: str | None = "002_health_fact"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) 加列：server_default='approved' 让旧行立刻拿到值，无需手动 UPDATE
    op.add_column(
        "skill_record",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="approved",
        ),
    )
    # 2) 索引：按 status 过滤的高频路径
    op.create_index("ix_skill_status", "skill_record", ["status"])
    # 3) 兜底：把任何遗漏的 NULL 改成 approved（理论上 server_default 已覆盖；
    #    但若数据从异构源导入，多一道保险）
    op.execute("UPDATE skill_record SET status='approved' WHERE status IS NULL")


def downgrade() -> None:
    op.drop_index("ix_skill_status", table_name="skill_record")
    op.drop_column("skill_record", "status")
