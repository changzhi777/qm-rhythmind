"""
run_qmd_server.py — 轻量 QMD 兼容服务

当 @tobi/qmd 不可用时，提供兼容的 /health、/mcp/query、/mcp/upsert 接口。
索引存储于 SQLite 数据库 knowledge.db 中（与 knowledge_article 共享）。

用法:
    python scripts/run_qmd_server.py                    # 默认 localhost:8181
    python scripts/run_qmd_server.py --port 8182        # 自定义端口
    python scripts/run_qmd_server.py --db sqlite:///data/knowledge.db
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from contextlib import asynccontextmanager
from collections import Counter

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logging.basicConfig(level=logging.INFO, format="%(asctime)s [qmd] %(message)s")
logger = logging.getLogger("qmd")

# ── 数据库层 ────────────────────────────────────────────────────────────────

DB_PATH: Path | None = None


def _get_db_path() -> Path:
    if DB_PATH:
        return DB_PATH
    return ROOT / "data" / "knowledge.db"


def _ensure_tables():
    """确保 qmd_docs 表存在。"""
    db = sqlite3.connect(str(_get_db_path()))
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS qmd_docs (
            id TEXT PRIMARY KEY,
            collection TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS ix_qmd_collection ON qmd_docs(collection)")
    db.commit()
    db.close()


# ── 简易搜索引擎 ────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """中文 + 英文分词（简易：按空格/标点切分，额外提取中文 2-gram）。"""
    # 提取英文单词
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    # 提取中文连续字符
    chinese_chars = re.findall(r"[一-鿿]+", text)
    # 中文 2-gram
    for segment in chinese_chars:
        for i in range(len(segment) - 1):
            words.append(segment[i : i + 2])
        words.append(segment)  # 完整词
    return [w for w in words if len(w) >= 2]


def _search(
    collection: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """基于关键词匹配的简易搜索。"""
    db = sqlite3.connect(str(_get_db_path()))
    cur = db.execute(
        "SELECT id, content, metadata_json FROM qmd_docs WHERE collection = ?",
        (collection,),
    )
    rows = cur.fetchall()
    db.close()

    if not rows:
        return []

    query_tokens = _tokenize(query)
    query_counter = Counter(query_tokens)
    if not query_counter:
        return []

    scored: list[tuple[float, str, str, dict]] = []
    for doc_id, content, metadata_json in rows:
        doc_tokens = _tokenize(content)
        doc_counter = Counter(doc_tokens)

        # 简单的 TF 余弦相似度
        dot_product = sum(
            query_counter[t] * doc_counter[t] for t in query_counter if t in doc_counter
        )
        query_norm = sum(v**2 for v in query_counter.values()) ** 0.5
        doc_norm = sum(v**2 for v in doc_counter.values()) ** 0.5

        if query_norm == 0 or doc_norm == 0:
            score = 0.0
        else:
            score = dot_product / (query_norm * doc_norm)

        if score > 0:
            try:
                metadata = json.loads(metadata_json)
            except json.JSONDecodeError:
                metadata = {}
            scored.append((score, doc_id, content, metadata))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": doc_id,
            "content": content[:2000],
            "score": round(score, 4),
            "metadata": metadata,
        }
        for score, doc_id, content, metadata in scored[:top_k]
    ]


# ── 知识库同步 ──────────────────────────────────────────────────────────────


def sync_from_knowledge_articles():
    """将 knowledge_article 表中的 project_context 同步到 qmd_docs。"""
    db = sqlite3.connect(str(_get_db_path()))
    # 确保 knowledge_article 表存在
    table_check = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_article'"
    ).fetchone()
    if not table_check:
        logger.warning("knowledge_article 表不存在，跳过同步")
        db.close()
        return

    rows = db.execute(
        """
        SELECT id, domain, title, summary, content, source, source_type, tags, relevance_score
        FROM knowledge_article WHERE domain = 'project_context'
        """
    ).fetchall()

    synced = 0
    for row in rows:
        art_id, domain, title, summary, content_json, source, source_type, tags, score = row

        # 构建可搜索文本
        try:
            content_obj = json.loads(content_json) if isinstance(content_json, str) else content_json
            sections_text = ""
            for sec in content_obj.get("sections", []):
                sections_text += f"{sec.get('heading', '')} {sec.get('body', '')[:1000]}"
        except (json.JSONDecodeError, TypeError):
            sections_text = str(content_json)[:2000]

        searchable = f"{title}\n{summary}\n{sections_text}"

        try:
            tags_list = json.loads(tags) if isinstance(tags, str) else (tags or [])
        except (json.JSONDecodeError, TypeError):
            tags_list = []

        metadata = {
            "title": title,
            "source": source,
            "source_type": source_type,
            "tags": tags_list,
            "article_id": art_id,
        }

        # upsert into qmd_docs
        doc_id = f"pc-{art_id}"
        db.execute(
            """
            INSERT OR REPLACE INTO qmd_docs (id, collection, content, metadata_json)
            VALUES (?, 'project_context', ?, ?)
            """,
            (doc_id, searchable, json.dumps(metadata, ensure_ascii=False)),
        )
        synced += 1

    db.commit()
    db.close()
    logger.info("sync_from_knowledge_articles: synced %d docs into project_context", synced)
    return synced


# ── Starlette 应用 ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: Starlette):
    _ensure_tables()
    synced = sync_from_knowledge_articles()
    logger.info("QMD server started, %d docs in project_context", synced)
    yield


app = Starlette(lifespan=lifespan)


async def health(request: Request) -> Response:
    return JSONResponse({"status": "ok"})


async def mcp_query(request: Request) -> Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    collection = body.get("collection", "project_context")
    query = body.get("query", "")
    top_k = min(body.get("topK", 5), 20)

    if not query:
        return JSONResponse({"results": [], "total": 0})

    results = _search(collection, query, top_k)
    logger.info("query collection=%s query=%r hits=%d", collection, query, len(results))
    return JSONResponse({"results": results, "total": len(results)})


async def mcp_upsert(request: Request) -> Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    collection = body.get("collection", "project_context")
    doc_id = body.get("id", "")
    content = body.get("content", "")
    metadata = body.get("metadata", {})

    if not doc_id:
        return JSONResponse({"error": "missing id"}, status_code=400)

    db = sqlite3.connect(str(_get_db_path()))
    db.execute(
        """
        INSERT OR REPLACE INTO qmd_docs (id, collection, content, metadata_json)
        VALUES (?, ?, ?, ?)
        """,
        (doc_id, collection, content, json.dumps(metadata, ensure_ascii=False)),
    )
    db.commit()
    db.close()

    logger.info("upsert collection=%s id=%s", collection, doc_id)
    return JSONResponse({"success": True})


async def mcp_delete(request: Request) -> Response:
    """删除集合或文档。"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    collection = body.get("collection", "")
    doc_filter = body.get("filter", {})

    db = sqlite3.connect(str(_get_db_path()))
    if doc_filter:
        # 按条件删除（简易：仅支持按 id 删除）
        doc_id = doc_filter.get("id", "")
        if doc_id:
            db.execute("DELETE FROM qmd_docs WHERE collection = ? AND id = ?", (collection, doc_id))
    else:
        # 删除整个集合
        db.execute("DELETE FROM qmd_docs WHERE collection = ?", (collection,))
    db.commit()
    db.close()

    logger.info("delete collection=%s filter=%s", collection, doc_filter)
    return JSONResponse({"success": True})


app.router.add_route("/health", health, methods=["GET"])
app.router.add_route("/mcp/query", mcp_query, methods=["POST"])
app.router.add_route("/mcp/upsert", mcp_upsert, methods=["POST"])
app.router.add_route("/mcp/delete", mcp_delete, methods=["POST"])


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="轻量 QMD 兼容服务")
    parser.add_argument("--port", type=int, default=8181, help="监听端口 (默认 8181)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0)")
    parser.add_argument("--db", default="", help="SQLite 数据库路径")
    parser.add_argument("--no-sync", action="store_true", help="跳过 knowledge_article 同步")
    args = parser.parse_args()

    if args.db:
        DB_PATH = Path(args.db)

    # 启动前同步
    _ensure_tables()
    if not args.no_sync:
        synced = sync_from_knowledge_articles()
        print(f"📚 已同步 {synced} 篇 project_context 文章到 QMD 索引")

    print(f"🚀 QMD 兼容服务启动: http://{args.host}:{args.port}")
    print(f"   集合: project_context ({synced} docs)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
