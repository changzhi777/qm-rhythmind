"""
tests/unit/test_knowledge_models.py — 知识库 ORM 单测

覆盖：
  - KnowledgeArticle CRUD + 索引
  - KnowledgeReference CRUD + CASCADE
  - relationship（article ↔ references 双向）
  - JSONB 字段（content/tags/key_findings）读写
"""
from __future__ import annotations

import pytest

from rhythmind.core.memory import manager as mem_manager
from rhythmind.db.knowledge_models import KnowledgeArticle, KnowledgeReference
from rhythmind.db.medical_models import (
    MedPatientProfile,  # noqa: F401 — 触发 Base.metadata 注册
)


def _session():
    """每次取 mem_manager.AsyncSessionLocal 属性，确保拿到 conftest 重置后的 factory。"""
    return mem_manager.AsyncSessionLocal


class TestKnowledgeArticle:
    @pytest.mark.asyncio
    async def test_create_article_minimal(self):
        """最小字段集创建（只 domain/title 必填）。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(
                    domain="osa",
                    title="阻塞性睡眠呼吸暂停筛查指南",
                )
                session.add(article)
            await session.refresh(article)
            assert article.id is not None
            assert article.domain == "osa"
            assert article.title == "阻塞性睡眠呼吸暂停筛查指南"
            # 默认值
            assert article.summary == ""
            assert article.content == {}
            assert article.source == ""
            assert article.source_type == "web"
            assert article.tags == []
            assert article.relevance_score == 0.0
            assert article.created_at is not None

    @pytest.mark.asyncio
    async def test_create_article_full(self):
        """完整字段创建。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(
                    domain="sleep_performance",
                    title="深度睡眠与运动表现",
                    summary="深度睡眠对运动恢复的影响综述",
                    content={"sections": [{"heading": "引言", "body": "...", "key_points": ["A", "B"]}]},
                    source="Sports Medicine Journal",
                    source_type="academic",
                    source_url="https://example.com/paper.pdf",
                    published_date="2024-03-15",
                    tags=["sleep", "recovery", "performance"],
                    relevance_score=0.85,
                )
                session.add(article)
            await session.refresh(article)
            assert article.content["sections"][0]["heading"] == "引言"
            assert "sleep" in article.tags
            assert article.relevance_score == 0.85

    @pytest.mark.asyncio
    async def test_query_by_domain(self):
        """按 domain 索引查询。"""
        async with _session()() as session:
            async with session.begin():
                session.add(KnowledgeArticle(domain="vo2max_training", title="VO2max 训练法"))
                session.add(KnowledgeArticle(domain="vo2max_training", title="VO2max 测试"))
                session.add(KnowledgeArticle(domain="osa", title="OSA 治疗"))
            async with _session()() as session:
                from sqlalchemy import select
                stmt = select(KnowledgeArticle).where(KnowledgeArticle.domain == "vo2max_training")
                result = (await session.execute(stmt)).scalars().all()
                assert len(result) >= 2
                assert all(a.domain == "vo2max_training" for a in result)

    @pytest.mark.asyncio
    async def test_update_relevance_score(self):
        """更新 relevance_score 字段。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(domain="osa", title="测试文章")
                session.add(article)
            article_id = article.id
        async with _session()() as session, session.begin():
            from sqlalchemy import select
            article = (await session.execute(
                select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
            )).scalar_one()
            article.relevance_score = 0.95
            # 重新查询验证持久化
        async with _session()() as session:
            from sqlalchemy import select
            refreshed = (await session.execute(
                select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
            )).scalar_one()
            assert refreshed.relevance_score == 0.95


class TestKnowledgeReference:
    @pytest.mark.asyncio
    async def test_create_reference_with_article(self):
        """创建文章 + 引用的关系数据。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(domain="osa", title="测试文章")
                session.add(article)
                await session.flush()
                ref = KnowledgeReference(
                    article_id=article.id,
                    ref_type="citation",
                    ref_title="AASM 2017 临床指南",
                    ref_url="https://aasm.org/guideline",
                    ref_authors="Kapur VK et al.",
                    ref_year=2017,
                    ref_journal="Journal of Clinical Sleep Medicine",
                    ref_doi="10.5664/jcsm.6746",
                    key_findings={"finding": "STOP-Bang ≥3 高风险", "evidence_level": "strong"},
                )
                session.add(ref)
            await session.refresh(ref)
            assert ref.id is not None
            assert ref.article_id == article.id
            assert ref.ref_year == 2017
            assert ref.key_findings["evidence_level"] == "strong"

    @pytest.mark.asyncio
    async def test_cascade_delete_references(self):
        """删除 article 时级联删除 references（FK CASCADE）。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(domain="osa", title="被删除的文章")
                session.add(article)
                await session.flush()
                ref1 = KnowledgeReference(article_id=article.id, ref_title="Ref 1", ref_type="citation")
                ref2 = KnowledgeReference(article_id=article.id, ref_title="Ref 2", ref_type="guideline")
                session.add_all([ref1, ref2])
                article_id = article.id
            ref_ids = (ref1.id, ref2.id)
        # 验证创建成功
        async with _session()() as session:
            from sqlalchemy import select
            refs_before = (await session.execute(
                select(KnowledgeReference).where(
                    KnowledgeReference.article_id == article_id
                )
            )).scalars().all()
            assert len(refs_before) == 2
        # 删除 article（应级联删除 refs）
        async with _session()() as session, session.begin():
            from sqlalchemy import select
            article = (await session.execute(
                select(KnowledgeArticle).where(KnowledgeArticle.id == article_id)
            )).scalar_one()
            await session.delete(article)
        # 验证 ref 已被级联删除
        async with _session()() as session:
            from sqlalchemy import select
            refs_after = (await session.execute(
                select(KnowledgeReference).where(
                    KnowledgeReference.id.in_(ref_ids)
                )
            )).scalars().all()
            assert len(refs_after) == 0

    @pytest.mark.asyncio
    async def test_relationship_back_populates(self):
        """article.references 反向关系。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(domain="osa", title="双向关系测试")
                session.add(article)
                await session.flush()
                for i in range(3):
                    session.add(KnowledgeReference(
                        article_id=article.id, ref_title=f"Ref {i}", ref_type="citation",
                    ))
            await session.refresh(article, attribute_names=["references"])
            assert len(article.references) == 3
            assert all(r.article_id == article.id for r in article.references)

    @pytest.mark.asyncio
    async def test_query_by_ref_type(self):
        """按 ref_type 索引查询。"""
        async with _session()() as session:
            async with session.begin():
                article = KnowledgeArticle(domain="vo2max", title="索引测试")
                session.add(article)
                await session.flush()
                session.add(KnowledgeReference(
                    article_id=article.id, ref_title="C1", ref_type="citation"
                ))
                session.add(KnowledgeReference(
                    article_id=article.id, ref_title="C2", ref_type="citation"
                ))
                session.add(KnowledgeReference(
                    article_id=article.id, ref_title="G1", ref_type="guideline"
                ))
            article_id = article.id
        async with _session()() as session:
            from sqlalchemy import select
            citations = (await session.execute(
                select(KnowledgeReference).where(
                    KnowledgeReference.article_id == article_id,
                    KnowledgeReference.ref_type == "citation",
                )
            )).scalars().all()
            assert len(citations) == 2
            assert all(r.ref_type == "citation" for r in citations)


class TestKnowledgeModelIndexes:
    """索引存在性测试（防止未来误删索引）。"""

    def test_article_indexes_exist(self):
        table = KnowledgeArticle.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_ka_domain" in index_names
        assert "ix_ka_source_type" in index_names

    def test_reference_indexes_exist(self):
        table = KnowledgeReference.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_kr_article_id" in index_names
        assert "ix_kr_ref_type" in index_names
