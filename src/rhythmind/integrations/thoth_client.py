"""
integrations/thoth_client.py — Thoth 知识库系统 API 客户端

Thoth v1.0.32 (10.10.10.15:80 nginx → :8765 FastAPI)
用作 rhythmind 的外部知识库后端，接收 AI 生成的报告/分析并入库。

使用：
  from rhythmind.integrations.thoth_client import ThothClient
  client = ThothClient()
  result = await client.ingest_document(
      title="用户 X 健康分析报告",
      content="# 报告正文...",
      domain="health",
      source_type="ai_analysis",
      tags=["weekly", "auto"],
  )

配置（环境变量，**不硬编码**）：
  THOTH_BASE_URL     - Thoth 服务地址（默认 https://10.10.10.15）
  THOTH_USERNAME     - API 账号用户名
  THOTH_PASSWORD     - API 账号密码
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, cast

import httpx
import structlog

from rhythmind.config import settings

log = structlog.get_logger(__name__)

# ── 异常层级 ────────────────────────────────────────────────────────────────


class ThothAPIError(Exception):
    """Thoth API 调用失败的基类异常。"""


class ThothAuthError(ThothAPIError):
    """认证失败（401/403）。"""


class ThothConnectionError(ThothAPIError):
    """网络/SSL 错误。"""


# ── Token 缓存 ──────────────────────────────────────────────────────────────

_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}
_CACHE_TTL = 3600  # 1 小时


# ── 客户端 ──────────────────────────────────────────────────────────────────


class ThothClient:
    """Thoth 知识库 API 客户端（异步 httpx + Token 缓存）。

    设计参考 rhythmind.integrations.feishu_client，简化版本（Thoth 暂无 SSO 多
    通道认证；直接 username/password login → bearer token）。
    """

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url: str = (base_url or settings.thoth_base_url).rstrip("/")
        self._username: str = username or settings.thoth_username
        self._password: str = password or settings.thoth_password
        self._timeout: float = timeout

    # ── 认证 ──────────────────────────────────────────────────────────────

    async def login(self) -> str:
        """登录 Thoth 获取 token（不依赖缓存）。

        Returns:
            bearer token 字符串

        Raises:
            ThothAuthError: 401/403
            ThothConnectionError: 网络/SSL 错
        """
        if not self._username or not self._password:
            raise ThothAuthError(
                "Thoth 凭据未配置（设置 THOTH_USERNAME / THOTH_PASSWORD）"
            )

        async with httpx.AsyncClient(timeout=self._timeout, verify=False) as cli:
            try:
                resp = await cli.post(
                    f"{self._base_url}/api/auth/login",
                    json={"username": self._username, "password": self._password},
                )
            except httpx.HTTPError as exc:
                raise ThothConnectionError(f"Thoth 连接失败: {exc}") from exc

        if resp.status_code == 401:
            raise ThothAuthError("Thoth 认证失败（用户名/密码错）")

        data = resp.json()
        token = data.get("access_token") or data.get("token") or ""
        if not token:
            raise ThothAuthError(f"Thoth 登录响应缺 token: {data}")

        return token

    async def _get_token(self) -> str:
        """取 token（缓存命中或重新登录）。"""
        cached = _token_cache.get("token", "")
        expires_at = _token_cache.get("expires_at", 0.0)
        if cached and time.time() < expires_at:
            return cast(str, cached)

        token = await self.login()
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + _CACHE_TTL
        log.info("thoth.token_refreshed", user=self._username)
        return token

    # ── 通用 HTTP ─────────────────────────────────────────────────────────

    async def _api_request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """通用 Thoth API 调用（自动加 Bearer + 错误处理）。"""
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=self._timeout, verify=False) as cli:
            try:
                if files is not None:
                    resp = await cli.request(
                        method, f"{self._base_url}{path}",
                        headers=headers, files=files, params=params,
                    )
                else:
                    resp = await cli.request(
                        method, f"{self._base_url}{path}",
                        headers=headers, json=json, params=params,
                    )
            except httpx.HTTPError as exc:
                raise ThothConnectionError(
                    f"Thoth {method} {path} 失败: {exc}"
                ) from exc

        if resp.status_code in (401, 403):
            # 401 可能是 token 过期，清缓存重试一次
            _token_cache["token"] = ""
            raise ThothAuthError(
                f"Thoth 鉴权失败 {resp.status_code}: {resp.text[:200]}"
            )

        if resp.status_code >= 400:
            raise ThothAPIError(
                f"Thoth {method} {path} 失败 {resp.status_code}: {resp.text[:200]}"
            )

        if resp.status_code == 204:
            return {}

        return cast(dict[str, Any], resp.json())

    # ── 业务方法 ─────────────────────────────────────────────────────────

    async def ingest_document(
        self,
        title: str,
        content: str,
        domain: str = "general",
        source_type: str = "ai_analysis",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """上传文档到 Thoth（multipart/form-data）。

        Args:
            title:       文档标题
            content:     文档正文（Markdown / 纯文本）
            domain:      领域分类（如 health / osa / vo2max_training）
            source_type: 来源类型（ai_analysis / web / academic）
            tags:        标签列表

        Returns:
            Thoth 响应 dict（含 document_id 等）

        Raises:
            ThothAPIError: API 错
            ThothAuthError: 鉴权错
        """
        files = {"file": (f"{title}.md", content.encode("utf-8"), "text/markdown")}
        data: dict[str, Any] = {"domain": domain, "source_type": source_type}
        if tags:
            data["tags"] = ",".join(tags)

        return await self._api_request(
            "POST", "/api/ingest/upload",
            files=files, params=data,
        )

    async def list_documents(
        self, limit: int = 20, offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列已上传文档。"""
        resp = await self._api_request(
            "GET", "/api/documents", params={"limit": limit, "offset": offset},
        )
        items = (
            resp.get("data", {}).get("items", [])
            if isinstance(resp, dict)
            else resp
        )
        return cast(list[dict[str, Any]], items)

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        """读文档详情。"""
        return await self._api_request("GET", f"/api/documents/{doc_id}")

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """全文检索文档。"""
        resp = await self._api_request(
            "POST", "/api/notes/search", json={"query": query, "limit": limit},
        )
        # Thoth 检索响应可能是 {"items": [...]} 或 直接 list
        if isinstance(resp, list):
            return cast(list[dict[str, Any]], resp)
        return cast(
            list[dict[str, Any]],
            resp.get("items", resp.get("results", [])),
        )

    async def health_check(self) -> bool:
        """连通性测试（不需认证）。"""
        async with httpx.AsyncClient(timeout=5, verify=False) as cli:
            try:
                resp = await cli.get(f"{self._base_url}/api/auth/me")
                # 401 表示服务在线但需认证（健康）；5xx 表示离线
                return resp.status_code in (200, 401)
            except httpx.HTTPError:
                return False


# ── 同步包装（方便非异步场景调用）─────────────────────────────────────────


def ingest_document_sync(**kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    """同步入口：用 `asyncio.run` 执行 `ThothClient.ingest_document`。

    用法：
        from rhythmind.integrations.thoth_client import ingest_document_sync
        result = ingest_document_sync(
            title="...", content="...", domain="health", tags=["x"]
        )

    凭据从 settings 自动读取（thoth_username/thoth_password），无需传递。
    """
    return asyncio.run(ThothClient().ingest_document(**kwargs))
