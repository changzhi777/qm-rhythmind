"""
知识库入库脚本 — 解析 docs/knowledge/*.md 并写入 knowledge_article + knowledge_reference 表

用法:
    python scripts/ingest_knowledge.py [--db sqlite:///data/knowledge.db]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rhythmind.db.knowledge_models import KnowledgeArticle, KnowledgeReference

KNOWLEDGE_DIR = ROOT / "docs" / "knowledge"


def parse_knowledge_file(filepath: Path) -> list[dict]:
    """解析单个知识库 Markdown 文件，返回条目列表。"""
    content = filepath.read_text(encoding="utf-8")
    domain_match = re.search(r"\*\*领域:\*\*\s*(\S+)", content)
    domain = domain_match.group(1) if domain_match else filepath.stem

    entries: list[dict] = []
    blocks = re.split(r"^## (KA-\S+?)：", content, flags=re.MULTILINE)

    for i in range(1, len(blocks), 2):
        article_id = blocks[i]
        body = blocks[i + 1]

        title_match = re.search(r"### 摘要\s*\n\s*(.+?)(?:\n|$)", body)
        title = title_match.group(1).strip() if title_match else article_id

        source_type_match = re.search(r"\*\*来源类型:\*\*\s*(\S+)", body)
        source_type = source_type_match.group(1) if source_type_match else "web"

        source_match = re.search(r"\*\*来源:\*\*\s*(.+?)(?:\n|$)", body)
        source = source_match.group(1).strip() if source_match else ""

        url_match = re.search(r"\*\*URL:\*\*\s*(\S+)", body)
        source_url = url_match.group(1) if url_match else None

        tags_match = re.search(r"\*\*标签:\*\*\s*\[(.+?)\]", body)
        tags = [t.strip() for t in tags_match.group(1).split(",")] if tags_match else []

        summary_match = re.search(r"### 摘要\s*\n(.+?)(?=\n###|\n---|\Z)", body, re.DOTALL)
        summary = summary_match.group(1).strip()[:2048] if summary_match else ""

        findings_match = re.search(r"### 关键发现\s*\n(.+?)(?=\n---|\n##|\Z)", body, re.DOTALL)
        key_points = []
        if findings_match:
            for line in findings_match.group(1).strip().splitlines():
                line = line.strip()
                if line.startswith("- "):
                    key_points.append(line[2:])

        relevance = 0.9 if domain == "osa" else 0.85

        entries.append({
            "domain": domain,
            "title": title[:512],
            "summary": summary,
            "content": {"sections": [{"heading": "关键发现", "key_points": key_points}]},
            "source": source,
            "source_type": source_type,
            "source_url": source_url,
            "tags": tags,
            "relevance_score": relevance,
            "raw_id": article_id,
            "key_points": key_points,
        })

    return entries


def ingest(db_url: str) -> None:
    """解析所有知识库文件并入库。"""
    engine = create_engine(db_url)

    KnowledgeArticle.__table__.create(engine, checkfirst=True)
    KnowledgeReference.__table__.create(engine, checkfirst=True)

    total_articles = 0
    total_refs = 0

    with Session(engine) as session:
        for filepath in sorted(KNOWLEDGE_DIR.glob("*.md")):
            entries = parse_knowledge_file(filepath)
            print(f"📄 {filepath.name}: {len(entries)} 条目")

            for entry in entries:
                existing = session.query(KnowledgeArticle).filter_by(
                    domain=entry["domain"], title=entry["title"],
                ).first()
                if existing:
                    print(f"  ⏭ {entry['raw_id']} 已存在(id={existing.id})，跳过")
                    continue

                article = KnowledgeArticle(
                    domain=entry["domain"],
                    title=entry["title"],
                    summary=entry["summary"],
                    content=entry["content"],
                    source=entry["source"],
                    source_type=entry["source_type"],
                    source_url=entry["source_url"],
                    tags=entry["tags"],
                    relevance_score=entry["relevance_score"],
                )
                session.add(article)
                session.flush()

                ref = KnowledgeReference(
                    article_id=article.id,
                    ref_type="citation",
                    ref_title=entry["source"],
                    ref_url=entry["source_url"],
                    key_findings={"key_points": entry["key_points"]},
                )
                session.add(ref)
                total_refs += 1

            total_articles += len(entries)

        session.commit()

    print(f"\n✅ 入库完成: {total_articles} 篇文章, {total_refs} 条引用")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识库入库脚本")
    parser.add_argument("--db", default="sqlite:///data/knowledge.db", help="数据库 URL")
    args = parser.parse_args()
    ingest(args.db)
