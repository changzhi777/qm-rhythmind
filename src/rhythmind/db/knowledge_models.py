"""
db/knowledge_models.py — 知识库 SQLAlchemy ORM 模型

2 张表：
  KnowledgeArticle    — 领域知识条目（结构化文章/摘要）
  KnowledgeReference  — 文献引用（学术/临床指南/权威来源）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rhythmind.core.memory.models import Base, JSONText


def _json(default: Any = None) -> Any:
    return JSONB(none_as_null=True).with_variant(JSONText(), "sqlite")


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_article"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="领域分类: osa / sleep_performance / vo2max_training",
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    content: Mapped[str] = mapped_column(
        _json(), nullable=False, default=dict,
        comment="结构化正文 JSON: {sections: [{heading, body, key_points}]}",
    )
    source: Mapped[str] = mapped_column(
        String(512), nullable=False, default="",
        comment="来源: 论文标题/指南名称/网站",
    )
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="web",
        comment="来源类型: academic / clinical_guideline / web / textbook",
    )
    source_url: Mapped[str] = mapped_column(String(1024), nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[Any] = mapped_column(
        _json(), nullable=False, default=list,
        comment="JSONB array: ['osa', 'spo2', 'screening']",
    )
    relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="与当前用户数据的关联度 0-1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    references: Mapped[list["KnowledgeReference"]] = relationship(
        back_populates="article", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_ka_domain", "domain"),
        Index("ix_ka_source_type", "source_type"),
    )


class KnowledgeReference(Base):
    __tablename__ = "knowledge_reference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("knowledge_article.id", ondelete="CASCADE"),
        nullable=False,
    )
    ref_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="citation",
        comment="引用类型: citation / guideline / clinical_trial / meta_analysis",
    )
    ref_title: Mapped[str] = mapped_column(String(512), nullable=False)
    ref_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ref_authors: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ref_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ref_journal: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ref_doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    key_findings: Mapped[str] = mapped_column(
        _json(), nullable=False, default=dict,
        comment="核心发现 JSON: {finding: string, evidence_level: string}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    article: Mapped["KnowledgeArticle"] = relationship(back_populates="references")

    __table_args__ = (
        Index("ix_kr_article_id", "article_id"),
        Index("ix_kr_ref_type", "ref_type"),
    )
