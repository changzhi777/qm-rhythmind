"""医疗数据表

Revision ID: 005_medical_tables
Revises: 004_audit_session_tables
Create Date: 2026-05-21

新增 5 张医疗数据表：
  - med_patient_profile  患者画像（脱敏）
  - med_diagnosis        诊断记录
  - med_clinical_event   统一事件时间线（入院/出院/手术/复诊/购药/化验）
  - med_lab_result       化验结果（结构化可查询）
  - med_medication       用药记录（当前/历史）

设计要点：
  - 所有表 user_id 关联主系统用户
  - JSONB metadata 字段存储扩展信息
  - event_type 枚举区分事件类型（同一张表存所有事件）
  - lab_result 带 reference_range + flag 支持趋势分析
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005_medical_tables"
down_revision: str | None = "004_audit_session_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── med_patient_profile ─────────────────────────────────────────────
    op.create_table(
        "med_patient_profile",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False, unique=True),
        sa.Column("name_hash", sa.String(64), nullable=False, server_default="''"),
        sa.Column("gender", sa.String(8), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("blood_type", sa.String(16), nullable=True),
        sa.Column("insurance_type", sa.String(64), nullable=True),
        sa.Column("insurance_id_hash", sa.String(64), nullable=True),
        sa.Column("address_region", sa.String(64), nullable=True),
        sa.Column(
            "demographics",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_med_profile_user", "med_patient_profile", ["user_id"], unique=True,
    )

    # ── med_diagnosis ───────────────────────────────────────────────────
    op.create_table(
        "med_diagnosis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("diagnosis_date", sa.Date(), nullable=False),
        sa.Column("diagnosis_name", sa.String(256), nullable=False),
        sa.Column("diagnosis_type", sa.String(32), nullable=False),
        sa.Column("icd_code", sa.String(16), nullable=True),
        sa.Column("hospital", sa.String(128), nullable=True),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "metadata",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_med_diag_user_date", "med_diagnosis", ["user_id", "diagnosis_date"],
    )
    op.create_index(
        "ix_med_diag_active", "med_diagnosis", ["user_id", "is_active"],
    )

    # ── med_clinical_event ──────────────────────────────────────────────
    op.create_table(
        "med_clinical_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "event_type",
            sa.String(32),
            nullable=False,
        ),
        sa.Column("hospital", sa.String(128), nullable=True),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("payment_method", sa.String(32), nullable=True),
        sa.Column("insurance_paid", sa.Float(), nullable=True),
        sa.Column("source_file", sa.String(256), nullable=True),
        sa.Column(
            "details",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_med_event_user_date", "med_clinical_event", ["user_id", "event_date"],
    )
    op.create_index(
        "ix_med_event_type", "med_clinical_event", ["user_id", "event_type"],
    )

    # ── med_lab_result ──────────────────────────────────────────────────
    op.create_table(
        "med_lab_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("test_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_name", sa.String(128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("value_str", sa.String(64), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("ref_range", sa.String(64), nullable=True),
        sa.Column("flag", sa.String(8), nullable=True),
        sa.Column("specimen", sa.String(32), nullable=True),
        sa.Column("hospital", sa.String(128), nullable=True),
        sa.Column("source_file", sa.String(256), nullable=True),
        sa.Column(
            "metadata",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_med_lab_user_test", "med_lab_result", ["user_id", "test_name", "test_date"],
    )
    op.create_index(
        "ix_med_lab_date", "med_lab_result", ["user_id", "test_date"],
    )

    # ── med_medication ──────────────────────────────────────────────────
    op.create_table(
        "med_medication",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("medication_name", sa.String(128), nullable=False),
        sa.Column("dose", sa.String(64), nullable=True),
        sa.Column("route", sa.String(32), nullable=True),
        sa.Column("frequency", sa.String(64), nullable=True),
        sa.Column("purpose", sa.String(128), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="'active'",
        ),
        sa.Column("prescriber", sa.String(64), nullable=True),
        sa.Column("hospital", sa.String(128), nullable=True),
        sa.Column("source_file", sa.String(256), nullable=True),
        sa.Column(
            "metadata",
            JSONB(none_as_null=True),
            nullable=False,
            server_default="'{}'",
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_med_med_user_status", "med_medication", ["user_id", "status"],
    )
    op.create_index(
        "ix_med_med_name", "med_medication", ["user_id", "medication_name"],
    )


def downgrade() -> None:
    op.drop_table("med_medication")
    op.drop_table("med_lab_result")
    op.drop_table("med_clinical_event")
    op.drop_table("med_diagnosis")
    op.drop_table("med_patient_profile")
