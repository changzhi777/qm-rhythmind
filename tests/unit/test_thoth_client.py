"""
tests/unit/test_thoth_client.py — ThothClient 客户端 Mock 单测

覆盖：
  - 认证（login / _get_token / 缓存命中 / 凭据缺失）
  - ingest_document（成功 / 鉴权失败 / 网络错）
  - list_documents / get_document / search
  - health_check
  - 异常类型（ThothAuthError / ThothConnectionError / ThothAPIError）

策略：用 `httpx_mock.add_callback` 注册 1 次（任意 URL 都路由到 callback），
callback 根据 URL 路径 + 方法返回对应 mock 响应。
"""
from __future__ import annotations

import httpx
import pytest

import rhythmind.integrations.thoth_client as tc
from rhythmind.integrations.thoth_client import (
    ThothAPIError,
    ThothAuthError,
    ThothClient,
    ThothConnectionError,
    ingest_document_sync,
)

# ── 全局 callback（所有测试共享路由逻辑）────────────────────────────────────────


def _thoth_callback(request: httpx.Request) -> httpx.Response:
    """统一路由：根据 URL path + method 返回 mock 响应。

    实际未被使用（thoth_mock fixture 直接注册另一 callback）。仅保留
    作为参考实现。
    """
    path = request.url.path
    method = request.method.upper()
    if path == "/api/auth/login" and method == "POST":
        return httpx.Response(200, json={"access_token": "tk-default"})
    if path == "/api/auth/me" and method == "GET":
        return httpx.Response(200, json={"username": "test"})
    return httpx.Response(404, json={"detail": f"not mocked: {method} {path}"})


# ── 路由控制 fixture：让每个测试用 `_thoth_router` 设置自定义响应 ───────────


@pytest.fixture
def thoth_router():
    """返回 router 实例，测试可用 `.set(method, path, status, json)` 预设响应。

    用法：
        async def test_x(client, thoth_router):
            thoth_router.set(
                "POST", "/api/ingest/upload", status=200, json={"document_id": "1"},
            )
            ...
    """
    return _MockRouter()


class _MockRouter:
    def __init__(self) -> None:
        self._routes: list[tuple[str, str, int, dict | None, str | None]] = []

    def set(self, method: str, path: str, *, status: int = 200,
            json: dict | None = None, text: str | None = None) -> None:
        self._routes.append((method.upper(), path, status, json, text))

    def response_for(self, request: httpx.Request) -> httpx.Response:
        for method, path, status, j, t in self._routes:
            if request.method.upper() == method and request.url.path == path:
                if t is not None:
                    return httpx.Response(status, text=t)
                return httpx.Response(status, json=j or {})
        # 未匹配：返 404 让测试失败（明确错）
        return httpx.Response(
            404, json={"detail": f"unmocked {request.method} {request.url.path}"},
        )


@pytest.fixture
def client() -> ThothClient:
    """默认 client，凭据已预设。"""
    return ThothClient(
        base_url="https://10.10.10.15",
        username="rhythmind_bot",
        password="test_password",
    )


# ── Token 缓存 fixture ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """每个测试前重置 _token_cache。"""
    tc._token_cache["token"] = ""
    tc._token_cache["expires_at"] = 0.0
    yield
    tc._token_cache["token"] = ""
    tc._token_cache["expires_at"] = 0.0


# ── 公共 mock fixture：让 callback 通过 thoth_router 路由 ──────────────


@pytest.fixture
def thoth_mock(httpx_mock, thoth_router):
    """组合：router 设置 + 全 mock 路由。

    用 `is_reusable=True` 让 callback 可被多个请求共享。
    """
    def callback(request: httpx.Request) -> httpx.Response:
        return thoth_router.response_for(request)
    httpx_mock.add_callback(callback, is_reusable=True)
    return thoth_router


# ── Construction / 凭据 ──────────────────────────────────────────────────


class TestConstruction:
    def test_uses_settings_by_default(self, monkeypatch):
        """无参数时从 settings 读 thoth_*。"""
        monkeypatch.setattr(tc.settings, "thoth_base_url", "https://thoth.example.com")
        monkeypatch.setattr(tc.settings, "thoth_username", "u")
        monkeypatch.setattr(tc.settings, "thoth_password", "p")
        c = ThothClient()
        assert c._base_url == "https://thoth.example.com"
        assert c._username == "u"
        assert c._password == "p"

    def test_explicit_args_override_settings(self, monkeypatch):
        """显式参数覆盖 settings。"""
        monkeypatch.setattr(tc.settings, "thoth_base_url", "https://old")
        c = ThothClient(base_url="https://new", username="n", password="p")
        assert c._base_url == "https://new"

    def test_base_url_strips_trailing_slash(self):
        """base_url 末尾 / 自动去除。"""
        c = ThothClient(base_url="https://x.com/", username="u", password="p")
        assert c._base_url == "https://x.com"


# ── Login ─────────────────────────────────────────────────────────────


class TestLogin:
    @pytest.mark.asyncio
    async def test_successful_login_returns_token(self, client, thoth_mock):
        thoth_mock.set("POST", "/api/auth/login",
                       json={"access_token": "tk-abc123", "user_id": 1})
        token = await client.login()
        assert token == "tk-abc123"

    @pytest.mark.asyncio
    async def test_login_falls_back_to_token_field(self, client, thoth_mock):
        """响应字段名 `token` 而非 `access_token` 时也能识别。"""
        thoth_mock.set("POST", "/api/auth/login",
                       json={"token": "tk-fallback", "user_id": 1})
        token = await client.login()
        assert token == "tk-fallback"

    @pytest.mark.asyncio
    async def test_401_raises_thoth_auth_error(self, client, thoth_mock):
        """401 抛 ThothAuthError。"""
        thoth_mock.set("POST", "/api/auth/login", status=401, text="Unauthorized")
        with pytest.raises(ThothAuthError, match="认证失败"):
            await client.login()

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_before_http(self, monkeypatch):
        """未配置凭据时直接抛 ThothAuthError（不发请求）。

        注意：需 monkeypatch settings 为空，详见 ThothClient 实现。
        空字符串会回退到 settings。
        """
        from rhythmind.config import settings as s
        monkeypatch.setattr(s, "thoth_username", "")
        monkeypatch.setattr(s, "thoth_password", "")
        c = ThothClient(base_url="https://x", username=None, password=None)
        with pytest.raises(ThothAuthError, match="凭据未配置"):
            await c.login()

    @pytest.mark.asyncio
    async def test_network_error_raises_connection_error(self, httpx_mock):
        """网络错抛 ThothConnectionError。"""
        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))
        c = ThothClient(base_url="https://x", username="u", password="p")
        with pytest.raises(ThothConnectionError, match="连接失败"):
            await c.login()


# ── Token 缓存 ──────────────────────────────────────────────────────


class TestGetToken:
    @pytest.mark.asyncio
    async def test_first_call_triggers_login(self, client, thoth_mock):
        """首次调用触发 login。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk-fresh"})
        token = await client._get_token()
        assert token == "tk-fresh"
        assert tc._token_cache["token"] == "tk-fresh"

    @pytest.mark.asyncio
    async def test_cached_token_reused_when_valid(self, client):
        """缓存未过期时直接返回缓存 token。"""
        import time
        tc._token_cache["token"] = "tk-cached"
        tc._token_cache["expires_at"] = time.time() + 3600
        token = await client._get_token()
        assert token == "tk-cached"


# ── IngestDocument ──────────────────────────────────────────────────


class TestIngestDocument:
    @pytest.mark.asyncio
    async def test_uploads_markdown_file_with_metadata(self, client, thoth_mock):
        """上传 markdown 文件 + metadata。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/ingest/upload",
                       json={"document_id": "doc-1", "status": "ingested"})

        result = await client.ingest_document(
            title="用户 X 健康分析",
            content="# 报告\n\n本周步数 80000。",
            domain="health",
            source_type="ai_analysis",
            tags=["weekly", "auto"],
        )
        assert result["document_id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_ingest_without_tags(self, client, thoth_mock):
        """无 tags 时不发送 tags 字段。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/ingest/upload", json={"document_id": "doc-2"})
        result = await client.ingest_document(
            title="no-tags", content="x", domain="general",
        )
        assert result["document_id"] == "doc-2"

    @pytest.mark.asyncio
    async def test_ingest_403_raises_auth_error(self, client, thoth_mock):
        """403 抛 ThothAuthError（清缓存）。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/ingest/upload", status=403, text="Forbidden")
        with pytest.raises(ThothAuthError, match="鉴权失败"):
            await client.ingest_document(title="x", content="x")
        # 缓存应被清空
        assert tc._token_cache["token"] == ""

    @pytest.mark.asyncio
    async def test_ingest_500_raises_api_error(self, client, thoth_mock):
        """500 抛 ThothAPIError。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/ingest/upload", status=500, text="ISE")
        with pytest.raises(ThothAPIError, match="500"):
            await client.ingest_document(title="x", content="x")


# ── List / Get / Search ────────────────────────────────────────────


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_returns_items_list(self, client, thoth_mock):
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("GET", "/api/documents",
                       json={"data": {"items": [{"id": "doc-1"}, {"id": "doc-2"}]}})
        items = await client.list_documents(limit=10)
        assert len(items) == 2
        assert items[0]["id"] == "doc-1"

    @pytest.mark.asyncio
    async def test_empty_response_returns_empty_list(self, client, thoth_mock):
        """响应无 data.items 时返空列表。"""
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("GET", "/api/documents", json={"data": {}})
        items = await client.list_documents()
        assert items == []


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_returns_document_dict(self, client, thoth_mock):
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("GET", "/api/documents/doc-42",
                       json={"id": "doc-42", "title": "X", "content": "..."})
        doc = await client.get_document("doc-42")
        assert doc["id"] == "doc-42"


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_items_from_response(self, client, thoth_mock):
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/notes/search",
                       json={"items": [{"id": "doc-1", "score": 0.9}]})
        results = await client.search("健康")
        assert len(results) == 1
        assert results[0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_empty_search_returns_empty(self, client, thoth_mock):
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/notes/search", json={"items": []})
        results = await client.search("nonexistent")
        assert results == []


# ── HealthCheck ────────────────────────────────────────────────────


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_200_returns_true(self, client, thoth_mock):
        thoth_mock.set("GET", "/api/auth/me", status=200)
        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_401_returns_true(self, client, thoth_mock):
        """401 表示服务在线但需认证（仍视为健康）。"""
        thoth_mock.set("GET", "/api/auth/me", status=401)
        assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_network_error_returns_false(self, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("refused"))
        c = ThothClient(base_url="https://x", username="u", password="p")
        assert await c.health_check() is False


# ── 同步入口 ─────────────────────────────────────────────────────


class TestIngestDocumentSync:
    def test_sync_wrapper_runs_async(self, thoth_mock, monkeypatch):
        """sync 入口从 settings 读凭据，monkeypatch 后正常工作。"""
        # sync 入口 ThothClient() 无参从 settings 读，需 monkeypatch
        from rhythmind.config import settings as s
        monkeypatch.setattr(s, "thoth_username", "rhythmind_bot")
        monkeypatch.setattr(s, "thoth_password", "test_password")
        thoth_mock.set("POST", "/api/auth/login", json={"access_token": "tk"})
        thoth_mock.set("POST", "/api/ingest/upload", json={"document_id": "sync-1"})
        result = ingest_document_sync(title="sync", content="x", domain="general")
        assert result["document_id"] == "sync-1"
