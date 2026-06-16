# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/memory/models.py — SQLAlchemy 2.0 ORM 模型（PostgreSQL-native）

表设计原则：
  1. namespace 列承载隔离语义，加复合唯一索引
  2. value_json → PostgreSQL JSONB，支持 JSON 路径查询和 GIN 加速
  3. tags → JSONB array，可直接用 @> 运算符做标签过滤
  4. 软删除（deleted_at），保留历史可追溯
  5. 时间字段统一带时区（TIMESTAMPTZ），存储 UTC

兼容性说明：
  单元测试继续使用 SQLite in-memory（Text 模拟 JSONB），
  编译期通过 _json_col() 辅助函数按方言自动选型。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TEXT, TypeDecorator

# ── 方言感知 JSON 列类型 ──────────────────────────────────────────────────

class JSONText(TypeDecorator[Any]):
    """
    SQLite 兼容的 JSON 类型（单元测试用）。

    PostgreSQL 生产环境使用原生 JSONB；
    SQLite in-memory 测试环境 fallback 到 Text + Python-side encode/decode。
    """
    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return value  # JSONB 已经反序列化


def _json_col(default: Any = None) -> Any:
    """
    返回按环境选型的 JSON 列类型。

    运行时通过 DATABASE_URL 判断：
      postgresql → JSONB（原生二进制 JSON，支持 GIN 索引）
      sqlite     → JSONText（Text + Python encode/decode）
    """
    # 延迟 import 避免循环
    from rhythmind.config import settings
    if "postgresql" in settings.database_url:
        return JSONB(none_as_null=True)
    return JSONText()


class Base(DeclarativeBase):
    pass


class AgentMemory(Base):
    """
    核心记忆表（PostgreSQL 生产版）。

    关键索引：
      ix_memory_ns_key    — 唯一约束，ON CONFLICT DO UPDATE 的锚点
      ix_memory_user_agent — 按 user+agent 快速筛选，最高频查询路径
      ix_memory_value_gin  — JSONB GIN 索引（PG 专用），支持 value @> 条件过滤
    """
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── 隔离三元组 ────────────────────────────────────────────────────────
    namespace: Mapped[str] = mapped_column(String(256), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)

    # ── 内容（JSONB in PG，JSONText in SQLite）────────────────────────────
    # 注意：mapped_column 需要在运行时确定 type，通过 deferred 工厂实现
    value_json: Mapped[Any] = mapped_column(
        "value_json",
        JSONB(none_as_null=True).with_variant(JSONText(), "sqlite"),
        nullable=False,
        default=dict,
    )
    tags: Mapped[Any] = mapped_column(
        "tags",
        JSONB(none_as_null=True).with_variant(JSONText(), "sqlite"),
        nullable=False,
        default=list,
    )
    mem_type: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # ── 时间（TIMESTAMPTZ，统一存 UTC）────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # 唯一约束：ON CONFLICT DO UPDATE 的锚点
        Index("ix_memory_ns_key", "namespace", "key", unique=True),
        # 高频筛选路径（非唯一）
        Index("ix_memory_user_agent", "user_id", "agent"),
        # GIN 索引仅在 PG 生效（SQLite 忽略 postgresql_using）
        Index(
            "ix_memory_value_gin",
            "value_json",
            postgresql_using="gin",
        ),
    )

    # ── 属性辅助（向后兼容旧代码中的 .value / .tag_list 访问）────────────

    @property
    def value(self) -> Any:
        """JSONB 直接返回 Python 对象；SQLite 路径已由 JSONText 处理。"""
        return self.value_json

    @value.setter
    def value(self, v: Any) -> None:
        self.value_json = v

    @property
    def tag_list(self) -> list[str]:
        tags = self.tags
        if isinstance(tags, list):
            return tags
        if isinstance(tags, str):
            return json.loads(tags)  # type: ignore[no-any-return]
        return []

    @tag_list.setter
    def tag_list(self, v: list[str]) -> None:
        self.tags = v

    def __repr__(self) -> str:
        return f"<AgentMemory ns={self.namespace} key={self.key}>"


class SkillRecord(Base):
    """
    技能记录表。

    SkillEngine 提取的 SKILL.md 片段持久化于此；
    仅当 status='approved' 时才同步到 QMD agent_skills collection（语义检索来源）。

    审核状态（status，v0.1.6+ 增加）:
      - "approved" — 已审核，可推 QMD；默认值（保证旧数据视为已审核）
      - "pending"  — 待审核；settings.skill_require_approval=True 时新写入的状态
      - "rejected" — 被 admin 拒绝；既不推 QMD 也不再使用
    """
    __tablename__ = "skill_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skill_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_task: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    synced_to_qmd: Mapped[bool] = mapped_column(nullable=False, default=False)

    # 默认值 'approved' 而非 'pending'，确保现有部署/旧数据不被破坏
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="approved",
        server_default="approved",
        index=True,
    )

    __table_args__ = (
        Index("ix_skill_agent_hash", "agent", "skill_hash", unique=True),
        Index("ix_skill_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SkillRecord agent={self.agent} hash={self.skill_hash} status={self.status}>"  # noqa: E501


class HealthFact(Base):
    """
    健康时序知识图谱（参考 MemPalace KG 模式）。

    每条记录描述 <user, subject, predicate, object> 的有效时间窗口。
    当事实发生变化时，旧记录通过 valid_until 标记过期，新记录写入，
    历史轨迹完整保留、可追溯。

    典型使用场景：
      用户目标变更：(user_001, user_goal, targets, {goal: marathon})
        → 旧 (user_goal, targets, {goal: 减脂}) valid_until = now()
      伤病状态：(user_001, injury, restricts, {area: 膝盖, sport: running})
        → 康复后 valid_until = now()
      训练基线：(user_001, baseline, heart_rate_avg, {value: 72.0})
        → 每次更新自动 invalidate 前值

    查询约定：
      当前有效 → WHERE valid_until IS NULL AND user_id = ?
      历史回溯 → WHERE user_id = ? ORDER BY valid_from
    """
    __tablename__ = "health_fact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # ── 三元组（SPO） ─────────────────────────────────────────────────────
    # subject   : 主体，如 "user_goal" / "injury" / "baseline"
    # predicate : 关系，如 "targets" / "restricts" / "heart_rate_avg"
    # object    : 值（JSONB），可存任意结构
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    predicate: Mapped[str] = mapped_column(String(128), nullable=False)
    object_json: Mapped[Any] = mapped_column(
        "object_json",
        JSONB(none_as_null=True).with_variant(JSONText(), "sqlite"),
        nullable=False,
        default=dict,
    )

    # ── 溯源 ──────────────────────────────────────────────────────────────
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    # ── 时序窗口（核心设计） ──────────────────────────────────────────────
    # valid_from  : 事实生效时间
    # valid_until : 事实过期时间（NULL = 当前有效）
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 当前有效事实的高频查询路径
        Index("ix_fact_user_subject", "user_id", "subject", "predicate"),
        # 按 user + 生效时间排序（历史回溯）
        Index("ix_fact_user_valid_from", "user_id", "valid_from"),
        # GIN 索引：object_json 内容过滤（PG 生效）
        Index("ix_fact_object_gin", "object_json", postgresql_using="gin"),
    )

    @property
    def is_current(self) -> bool:
        """True = 当前有效（未被 invalidate）。"""
        return self.valid_until is None

    @property
    def object(self) -> Any:
        return self.object_json

    @object.setter
    def object(self, v: Any) -> None:
        self.object_json = v

    def __repr__(self) -> str:
        status = "current" if self.is_current else "expired"
        return (
            f"<HealthFact user={self.user_id} "
            f"({self.subject}, {self.predicate}) "
            f"status={status}>"
        )


class AuditLog(Base):
    """
    运营审计日志表（PG 持久化，配合 migration 004）。

    存储所有 audit_log() 调用记录，用于：
      - 合规审计追溯（R-3 防篡改要求）
      - 安全事件调查（登录异常、权限变更）
      - 操作审计（skill approve/reject、privacy delete 等）

    注意：只存元数据，不存 PII（user_id + event + fields）。
    """
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_event_created", "event", "created_at"),
    )


class UserSession(Base):
    """
    用户会话表（PG 备份，配合 migration 004）。

    用于：
      - 审计追溯（谁在什么时候做了什么）
      - 用户行为分析（intents_used 聚合）
      - 会话时长统计（duration_ms）

    与 Redis SessionCache 成主备关系：
      - Redis：实时热数据（TTL 30min）
      - PG：持久化冷数据（长期分析用）
    """
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intents_used: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # noqa: E501
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_session_user_created", "user_id", "created_at"),
    )
