"""LLM 调用本地观测表

Revision ID: 007_llm_call_log
Revises: 006_knowledge_tables
Create Date: 2026-06-25

背景:
  原 /api/v1/llm-observe/* 直接查 Langfuse PG 的 observations 表,
  本地环境 Langfuse 未启用时返回 503(无数据)。

修复:
  新增 llm_call_log 本地表,@observe_llm 装饰器始终把 LLM 调用记到这里,
  /llm-observe/* 路由在 Langfuse 不可用时 fallback 到本地表。

字段说明:
  - id        自增主键
  - user_id   调用方 user_id(可空,适配器层调用时无 user context)
  - agent     哪个 agent/router 调用 (如 'adapter_router' / 'coach_agent')
  - model     实际模型名 (如 'gemma-4-12B-it-4bit')
  - start_time/end_time  调用起止时间
  - latency_ms  延迟(毫秒)
  - total_tokens 估算的 token 总数
  - total_cost 估算的 USD 成本
  - level     DEFAULT / WARNING / ERROR (与 Langfuse v2 对齐)
  - success   成功/失败
  - error_msg 失败信息(可空)
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_llm_call_log"
down_revision: str | None = "006_knowledge_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_call_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("agent", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("model", sa.String(128), nullable=False, server_default="unknown"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("level", sa.String(16), nullable=False, server_default="DEFAULT"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    # 时间倒序索引(指标聚合查询)
    op.create_index("idx_llm_call_log_created_at", "llm_call_log", ["created_at"], unique=False)
    # user_id 索引(多用户隔离)
    op.create_index("idx_llm_call_log_user_id", "llm_call_log", ["user_id"], unique=False)
    # model 索引(模型分布查询)
    op.create_index("idx_llm_call_log_model", "llm_call_log", ["model"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_llm_call_log_model", table_name="llm_call_log")
    op.drop_index("idx_llm_call_log_user_id", table_name="llm_call_log")
    op.drop_index("idx_llm_call_log_created_at", table_name="llm_call_log")
    op.drop_table("llm_call_log")
