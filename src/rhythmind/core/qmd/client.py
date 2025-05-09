# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/qmd/client.py — QMD HTTP 客户端（异步，带 namespace 安全隔离）

QMD（tobi/qmd）是本地运行的混合检索引擎：
  BM25 + 向量 + LLM rerank，监听在 localhost:8181，
  通过 /mcp/query 和 /mcp/upsert 暴露 MCP 兼容接口。

安全红线：
  _enforce_namespace() 在任何涉及 user_ 前缀的集合操作前强制校验，
  集合名必须以 user_{user_id}_ 开头，否则抛出 SecurityError。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import httpx

from rhythmind.config import settings

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """跨用户命名空间访问尝试。"""


class QMDUnavailableError(Exception):
    """QMD 服务不可达（降级用）。"""


# QMD 标准集合名
QMD_COLLECTION_AGENT_SKILLS = "agent_skills"
QMD_COLLECTION_KNOWLEDGE_BASE = "health_knowledge"
QMD_COLLECTION_HUNAN_DIET = "hunan_diet"


def _user_collection(user_id: str, suffix: str) -> str:
    """生成用户专属集合名：user_{id}_{suffix}"""
    safe_id = "".join(c if c.isalnum() else "_" for c in user_id)
    return f"user_{safe_id}_{suffix}"


class QMDClient:
    """
    QMD HTTP 客户端。

    使用 httpx.AsyncClient 长连接池，超时受 settings.qmd_timeout 控制。
    设计为无状态，可在多个 Agent 间安全共享同一实例。
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.qmd_url).rstrip("/")
        self._timeout = timeout or settings.qmd_timeout
        # 懒初始化，避免模块导入时触发代理检测
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
                trust_env=False,   # 忽略系统代理，防止沙盒 SOCKS 问题
            )
        return self._client

    async def query(
        self,
        collection: str,
        query: str,
        user_ns: str = "",
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        语义检索。

        Args:
            collection: 集合名（user_* 集合需传 user_ns 用于安全校验）
            query:      自然语言查询
            user_ns:    当前请求用户 ID（安全校验用）
            top_k:      返回条数，默认取 settings.qmd_top_k
            filters:    附加 metadata 过滤条件
        Returns:
            [{id, content, score, metadata}, ...]
        """
        safe_collection = self._enforce_namespace(collection, user_ns)
        payload: dict[str, Any] = {
            "collection": safe_collection,
            "query": query,
            "topK": top_k or settings.qmd_top_k,
        }
        if filters:
            payload["filters"] = filters

        try:
            resp = await self._get_client().post("/mcp/query", json=payload)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            logger.debug(
                "qmd.query collection=%s query=%r hits=%d",
                safe_collection, query, len(results),
            )
            return results
        except httpx.ConnectError as e:
            logger.warning("qmd.query unavailable: %s", e)
            raise QMDUnavailableError(f"QMD not reachable at {self._base_url}") from e
        except httpx.HTTPStatusError as e:
            logger.error("qmd.query http_error status=%d", e.response.status_code)
            return []

    async def upsert(
        self,
        collection: str,
        doc_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        user_ns: str = "",
    ) -> bool:
        """
        插入或更新单个文档。

        Returns:
            True 表示写入成功。
        """
        safe_collection = self._enforce_namespace(collection, user_ns)
        payload: dict[str, Any] = {
            "collection": safe_collection,
            "id": doc_id,
            "content": content,
            "metadata": metadata or {},
        }
        try:
            resp = await self._get_client().post("/mcp/upsert", json=payload)
            resp.raise_for_status()
            logger.debug("qmd.upsert collection=%s id=%s", safe_collection, doc_id)
            return True
        except (httpx.ConnectError, httpx.HTTPStatusError) as e:
            logger.error("qmd.upsert failed: %s", e)
            return False

    async def index_skill(
        self,
        agent: str,
        skill_content: str,
        task_type: str = "",
    ) -> bool:
        """
        将技能片段写入 agent_skills 集合。

        doc_id = "skill_{agent}_{hash}" 保证幂等。
        """
        skill_hash = hashlib.sha256(skill_content.encode()).hexdigest()[:16]
        doc_id = f"skill_{agent}_{skill_hash}"
        return await self.upsert(
            collection=QMD_COLLECTION_AGENT_SKILLS,
            doc_id=doc_id,
            content=skill_content,
            metadata={
                "agent": agent,
                "task_type": task_type,
                "hash": skill_hash,
            },
        )

    async def index_user_memory(
        self,
        user_id: str,
        key: str,
        content: str,
    ) -> bool:
        """
        将用户记忆写入用户专属集合（用于长期语义检索）。

        集合名：user_{user_id}_memory
        """
        collection = _user_collection(user_id, "memory")
        doc_id = f"mem_{user_id}_{hashlib.md5(key.encode()).hexdigest()[:8]}"
        return await self.upsert(
            collection=collection,
            doc_id=doc_id,
            content=content,
            metadata={"user_id": user_id, "key": key},
            user_ns=user_id,
        )

    async def query_user_memory(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """查询用户专属记忆集合。"""
        collection = _user_collection(user_id, "memory")
        return await self.query(
            collection=collection,
            query=query,
            user_ns=user_id,
            top_k=top_k,
        )

    async def close(self) -> None:
        """应用关闭时调用，释放连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 安全校验 ──────────────────────────────────────────────────────────

    @staticmethod
    def _enforce_namespace(collection: str, user_ns: str) -> str:
        """
        安全红线：强制校验 user_* 集合的命名空间。

        规则：
          - 非 user_ 前缀的集合（如 agent_skills）直接放行
          - user_ 前缀的集合必须以 user_{user_ns}_ 开头
          - user_ns 为空时访问 user_ 集合 → SecurityError

        Raises:
            SecurityError: namespace 不匹配或 user_ns 未提供
        """
        if not collection.startswith("user_"):
            return collection  # 公共集合，直接放行

        if not user_ns:
            raise SecurityError(
                f"Accessing user collection '{collection}' requires user_ns"
            )

        safe_ns = "".join(c if c.isalnum() else "_" for c in user_ns)
        expected_prefix = f"user_{safe_ns}_"

        if not collection.startswith(expected_prefix):
            raise SecurityError(
                f"Collection namespace mismatch: "
                f"expected prefix '{expected_prefix}', got '{collection}'"
            )

        return collection
