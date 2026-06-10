"""
ingest_claude_md.py — 项目上下文入库脚本

将 CLAUDE.md（26 个模块）和 Auto Memory（~12 个 .md）解析后写入
knowledge_article + knowledge_reference 表，并索引到 QMD 向量库。

用法:
    python scripts/ingest_claude_md.py                    # 全量入库 + QMD 索引
    python scripts/ingest_claude_md.py --no-qmd           # 仅入库 DB，不索引 QMD
    python scripts/ingest_claude_md.py --db postgresql:// # 指定数据库
    python scripts/ingest_claude_md.py --dry-run          # 预览，不写入
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from rhythmind.db.knowledge_models import KnowledgeArticle, KnowledgeReference

# ── 源目录 ──────────────────────────────────────────────────────────────
CLAUDE_MD_DIRS = [
    ROOT,                                    # 项目根 CLAUDE.md
    ROOT / "frontend",                       # 前端 CLAUDE.md
    ROOT / "frontend" / "src" / "app",
    ROOT / "frontend" / "src" / "components" / "charts",
    ROOT / "frontend" / "src" / "components" / "layout",
    ROOT / "frontend" / "src" / "lib",
    ROOT / "frontend" / "src" / "lib" / "stores",
    ROOT / "frontend" / "tests",
    ROOT / "web",
    ROOT / "scripts",
    ROOT / "docs" / "templates",
    ROOT / "docs" / "workflows",
    ROOT / "docs" / "knowledge",
    SRC_DIR / "rhythmind" / "api",
    SRC_DIR / "rhythmind" / "integrations",
    SRC_DIR / "rhythmind" / "adapters",
    SRC_DIR / "rhythmind" / "ingestion",
    SRC_DIR / "rhythmind" / "agents",
    SRC_DIR / "rhythmind" / "core",
    SRC_DIR / "rhythmind" / "core" / "cache",
    SRC_DIR / "rhythmind" / "orchestrator",
    SRC_DIR / "rhythmind" / "mcp",
    SRC_DIR / "rhythmind" / "db",
    SRC_DIR / "rhythmind" / "privacy",
    SRC_DIR / "rhythmind" / "audit",
    SRC_DIR / "rhythmind" / "observability",
]

MEMORY_DIR = Path.home() / ".claude" / "projects" / "-Users-mac-Documents-trae-projects-qm-rhythmind" / "memory"

DOMAIN = "project_context"

# ── 工具函数 ────────────────────────────────────────────────────────────


def _slug(text: str, max_len: int = 80) -> str:
    """生成简短标识符。"""
    slug = re.sub(r"[^\w]+", "-", text.lower()).strip("-")
    return slug[:max_len]


def _extract_changelog(content: str) -> list[str]:
    """从 CLAUDE.md 中提取 Changelog 条目。"""
    m = re.search(r"##?\s*变更记录.*?\n((?:.|\n)*?)(?=\n##|\Z)", content)
    if not m:
        return []
    entries = []
    for line in m.group(1).strip().splitlines():
        line = line.strip()
        if line.startswith("- **"):
            entries.append(re.sub(r"\*\*|✅\s*", "", line).strip("- "))
    return entries


def _parse_memory_frontmatter(content: str) -> dict:
    """从 memory .md 文件的 YAML frontmatter 中提取元数据。"""
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        kv = re.match(r"(\w[\w\s]*):\s*(.+)", line)
        if kv:
            meta[kv.group(1).strip()] = kv.group(2).strip()
    return meta


def _extract_memory_body(content: str) -> str:
    """提取 memory 文件去掉 frontmatter 后的正文。"""
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL).strip()


# ── 解析函数 ────────────────────────────────────────────────────────────


def parse_claude_md(filepath: Path) -> list[dict]:
    """将 CLAUDE.md 按 ## 二级标题切片，返回条目列表。"""
    content = filepath.read_text(encoding="utf-8")
    module_name = filepath.parent.name if filepath.parent.name != ROOT.name else "workspace"
    if module_name in ("qm-rhythmind", "src", "components"):
        module_name = filepath.parent.parent.name if filepath.parent.parent.name != "src" else filepath.parent.name

    # 取第一行标题作为模块名
    first_line = content.strip().split("\n")[0].lstrip("# ")
    if first_line and len(first_line) < 100:
        module_name = first_line

    entries: list[dict] = []
    changelog = _extract_changelog(content)

    # 按 ## 切片
    sections = re.split(r"^## (.*?)$", content, flags=re.MULTILINE)
    intro = sections[0]  # 标题行 + 元信息（第一个 ## 之前的内容）

    # 生成一个总览条目
    overview_title = module_name
    overview_summary = ""
    for line in intro.strip().splitlines():
        line = line.strip()
        if line.startswith("> **") and ":" in line:
            overview_summary += line.strip("> ").strip() + "; "
        if line.startswith("## 模块职责") or line.startswith("## 项目愿景"):
            # 取职责描述作为摘要
            pass

    overview_summary = overview_summary[:500] or intro.strip()[:500]

    entries.append({
        "raw_id": f"OVERVIEW-{_slug(module_name)}",
        "domain": DOMAIN,
        "title": f"{module_name} — 模块总览",
        "summary": overview_summary,
        "content": {
            "sections": [{"heading": "模块总览", "body": intro.strip()[:4000]}],
            "changelog": changelog,
        },
        "source": str(filepath.relative_to(ROOT)),
        "source_type": "project_doc",
        "source_url": None,
        "tags": [DOMAIN, "module", _slug(module_name)],
        "relevance_score": 0.95,
    })

    # 按 ## 二级标题切片
    for i in range(1, len(sections), 2):
        heading = sections[i].strip()
        body = sections[i + 1].strip() if i + 1 < len(sections) else ""

        # 跳过非实体章节（变更记录、相关文件等纯参考型章节只做索引不做详细条目）
        skip_headings = {"变更记录", "相关文件清单", "相关文件", "运行与开发", "编码规范", "测试结构"}
        if heading in skip_headings or heading.startswith("相关"):
            continue

        body_short = body[:3000]
        summary = body[:300] if body else heading
        # 用第一个表格行或列表项作为摘要
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("|") or stripped.startswith("- ") or stripped.startswith("1. "):
                summary = stripped.strip("| -1234567890. ") + "…"
                break

        entries.append({
            "raw_id": f"{_slug(module_name)}-{_slug(heading)}",
            "domain": DOMAIN,
            "title": f"{module_name} › {heading}",
            "summary": summary[:500],
            "content": {
                "sections": [{"heading": heading, "body": body_short}],
                "changelog": changelog,
            },
            "source": str(filepath.relative_to(ROOT)),
            "source_type": "project_doc",
            "source_url": None,
            "tags": [DOMAIN, "module", _slug(module_name), _slug(heading)],
            "relevance_score": 0.90,
        })

    return entries


def parse_memory_file(filepath: Path) -> dict | None:
    """解析单个 Auto Memory .md 文件。"""
    if filepath.name in ("MEMORY.md",):
        return None  # 索引文件跳过，正文已在其他文件中

    content = filepath.read_text(encoding="utf-8")
    meta = _parse_memory_frontmatter(content)
    body = _extract_memory_body(content)

    title = meta.get("description", filepath.stem)
    mem_type = meta.get("type", "project")

    # 提取关联标记 [[...]]
    linked = re.findall(r"\[\[(.+?)\]\]", body)
    tags = [DOMAIN, "memory", mem_type] + linked

    return {
        "raw_id": f"MEM-{filepath.stem}",
        "domain": DOMAIN,
        "title": f"[Memory:{mem_type}] {title}",
        "summary": body[:300] if body else "",
        "content": {
            "sections": [{"heading": title, "body": body[:3000]}],
            "links_to": linked,
        },
        "source": f"memory/{filepath.name}",
        "source_type": "project_memory",
        "source_url": None,
        "tags": tags,
        "relevance_score": 0.85,
    }


# ── 入库 ────────────────────────────────────────────────────────────────


def ingest(db_url: str, dry_run: bool = False, index_qmd: bool = True) -> dict:
    """解析所有源文件并入库。返回统计信息。"""
    engine = create_engine(db_url)

    if not dry_run:
        KnowledgeArticle.__table__.create(engine, checkfirst=True)
        KnowledgeReference.__table__.create(engine, checkfirst=True)

    stats = {"claude_md_files": 0, "memory_files": 0, "articles": 0, "refs": 0, "skipped": 0}

    with Session(engine) as session:
        # ── CLAUDE.md 文件 ──
        for dirpath in CLAUDE_MD_DIRS:
            claude_path = dirpath / "CLAUDE.md"
            if not claude_path.exists():
                continue
            stats["claude_md_files"] += 1
            entries = parse_claude_md(claude_path)
            print(f"📄 {claude_path.relative_to(ROOT)}: {len(entries)} 个切片")

            for entry in entries:
                existing = session.query(KnowledgeArticle).filter_by(
                    domain=DOMAIN,
                    title=entry["title"],
                ).first()
                if existing:
                    stats["skipped"] += 1
                    continue

                if dry_run:
                    print(f"  → [{entry['raw_id']}] {entry['title'][:80]}")
                    stats["articles"] += 1
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
                    ref_type="project_doc",
                    ref_title=entry["source"],
                    key_findings={"sections": len(entry["content"].get("sections", []))},
                )
                session.add(ref)
                stats["refs"] += 1
                stats["articles"] += 1

        # ── Memory 文件 ──
        if MEMORY_DIR.exists():
            for filepath in sorted(MEMORY_DIR.glob("*.md")):
                if filepath.name == "MEMORY.md":
                    continue
                stats["memory_files"] += 1
                entry = parse_memory_file(filepath)
                if entry is None:
                    continue

                existing = session.query(KnowledgeArticle).filter_by(
                    domain=DOMAIN,
                    title=entry["title"],
                ).first()
                if existing:
                    stats["skipped"] += 1
                    continue

                if dry_run:
                    print(f"  → [{entry['raw_id']}] {entry['title'][:80]}")
                    stats["articles"] += 1
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
                stats["articles"] += 1

        if not dry_run:
            session.commit()

    # ── QMD 索引 ──
    qmd_count = 0
    if index_qmd and not dry_run:
        qmd_count = _index_into_qmd(db_url)

    stats["qmd_indexed"] = qmd_count
    return stats


def _index_into_qmd(db_url: str) -> int:
    """将 project_context 文章索引到 QMD 向量库。"""
    try:
        from rhythmind.core.qmd import QMDClient
    except ImportError:
        print("⚠ QMDClient 不可用，跳过向量索引")
        return 0

    engine = create_engine(db_url)
    client = QMDClient()
    count = 0

    with Session(engine) as session:
        articles = session.query(KnowledgeArticle).filter_by(domain=DOMAIN).all()
        for article in articles:
            text_for_index = f"{article.title}\n{article.summary}"
            try:
                # 使用 upsert 写入 QMD project_context 集合
                import asyncio
                async def _upsert():
                    return await client.upsert(
                        collection="project_context",
                        doc_id=f"pc-{article.id}",
                        content=text_for_index,
                        metadata={
                            "title": article.title,
                            "source": article.source,
                            "source_type": article.source_type,
                            "tags": article.tags if isinstance(article.tags, list) else [],
                        },
                    )
                asyncio.get_event_loop().run_until_complete(_upsert())
                count += 1
            except Exception as e:
                print(f"  ⚠ QMD 索引失败 [{article.title[:60]}]: {e}")

    print(f"  🧠 QMD 索引: {count}/{len(articles) if 'articles' in dir() else '?'} 条")
    return count


# ── CLI ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="项目上下文入库 — CLAUDE.md + Memory → knowledge_article + QMD",
    )
    parser.add_argument(
        "--db", default="sqlite:///data/knowledge.db",
        help="数据库 URL（默认 sqlite:///data/knowledge.db）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览模式，不写入数据库",
    )
    parser.add_argument(
        "--no-qmd", action="store_true",
        help="跳过 QMD 向量索引",
    )
    args = parser.parse_args()

    print(f"🔍 扫描 CLAUDE.md ({len(CLAUDE_MD_DIRS)} 个目录) + Memory ({MEMORY_DIR})")
    print(f"📦 数据库: {args.db}")
    if args.dry_run:
        print("👀 DRY RUN 模式 — 不会写入")
    print()

    result = ingest(args.db, dry_run=args.dry_run, index_qmd=not args.no_qmd)

    print()
    print(f"📊 统计:")
    print(f"   CLAUDE.md 文件: {result['claude_md_files']}")
    print(f"   Memory 文件:   {result['memory_files']}")
    print(f"   入库文章:      {result['articles']}")
    print(f"   引用条目:      {result['refs']}")
    print(f"   跳过(已存在):  {result['skipped']}")
    print(f"   QMD 索引:      {result.get('qmd_indexed', 'N/A')}")
    print()
    if not args.dry_run and result['articles'] > 0:
        print("✅ 入库完成。MCP rhythmind_search 可用 collection='project_context' 检索。")
    elif result['articles'] == 0:
        print("ℹ️  所有条目均已存在，无新增。")
