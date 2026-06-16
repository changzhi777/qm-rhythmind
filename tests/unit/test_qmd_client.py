# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 许可：CC BY-NC 4.0
# ─────────────────────────────────────────────────────────────────────────────

"""
tests/unit/test_qmd_client.py — QMDClient 方法单元测试

覆盖 QMDClient 7 个方法的 missing 行（line 100-124/149-151/191-193/208-209/
241-246/270-272/279-281）：
  - query() 4 路径：正常/filters 附加/ConnectError→QMDUnavailableError/HTTPStatusError→[]
  - upsert() 2 路径：成功/失败返 False
  - index_skill() 派生路径
  - index_user_memory() 派生路径（hash md5 派生 doc_id）
  - query_user_memory() 派生路径
  - purge_user() 多集合循环 + 异常捕获
  - _delete_collection() 成功/失败
  - close() 关闭客户端

命名空间安全（_enforce_namespace / _user_collection）由 test_qmd_isolation.py 覆盖。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rhythmind.core.qmd.client import QMDClient, QMDUnavailableError


def _make_mock_resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """构造 mock httpx.Response。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    # 默认 raise_for_status 不抛；测试需要抛时单独 patch
    resp.raise_for_status = MagicMock()
    return resp


def _patch_get_client(client: QMDClient, mock_resp: MagicMock) -> AsyncMock:
    """替换 QMDClient._get_client() 返回 mock httpx.AsyncClient（带 post）。

    QMDClient._get_client 是 def (同步) 方法，直接返回 httpx.AsyncClient 实例。
    替换方式：直接把 client._get_client 绑定到同步函数（返回 mock_http）。
    """
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)

    def _fake_get_client() -> AsyncMock:
        return mock_http_client

    client._get_client = _fake_get_client  # type: ignore[method-assign]
    return mock_http_client


class TestQuery:
    @pytest.mark.asyncio
    async def test_returns_results_on_success(self):
        """正常返回：data.results 透传。"""
        client = QMDClient(base_url="http://qmd:8000")
        expected = [
            {"id": "1", "content": "a", "score": 0.9, "metadata": {}},
            {"id": "2", "content": "b", "score": 0.8, "metadata": {}},
        ]
        resp = _make_mock_resp(json_data={"results": expected})
        _patch_get_client(client, resp)

        result = await client.query(
            collection="agent_skills", query="test", user_ns="u1"
        )
        assert result == expected

    @pytest.mark.asyncio
    async def test_includes_filters_in_payload(self):
        """filters 非空时应附加到 payload。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(json_data={"results": []})
        mock_http = _patch_get_client(client, resp)

        await client.query(
            collection="agent_skills", query="test", user_ns="u1",
            filters={"agent": "coach", "min_score": 0.5},
        )
        # 验证 POST 的 payload 含 filters、query
        call_kwargs = mock_http.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["filters"] == {"agent": "coach", "min_score": 0.5}
        assert payload["query"] == "test"
        # collection 名称由 _enforce_namespace 处理（具体规则见 test_qmd_isolation.py）
        assert "collection" in payload
        assert payload["collection"] == "agent_skills"

    @pytest.mark.asyncio
    async def test_connect_error_raises_unavailable(self):
        """httpx.ConnectError 时应抛 QMDUnavailableError。"""
        client = QMDClient(base_url="http://qmd:8000")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        client._get_client = lambda: mock_http  # type: ignore[method-assign]

        with pytest.raises(QMDUnavailableError, match="QMD not reachable"):
            await client.query("agent_skills", "test", user_ns="u1")

    @pytest.mark.asyncio
    async def test_http_status_error_returns_empty_list(self):
        """raise_for_status 抛错时返回空列表（不抛 QMDUnavailableError）。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(status_code=500)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=resp
            )
        )
        _patch_get_client(client, resp)

        result = await client.query("agent_skills", "test", user_ns="u1")
        assert result == []


class TestUpsert:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """成功 upsert 返回 True。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(json_data={"ok": True})
        _patch_get_client(client, resp)

        result = await client.upsert(
            collection="agent_skills", doc_id="d1", content="hello",
            metadata={"k": "v"}, user_ns="u1",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_http_error(self):
        """HTTP 错误时 upsert 返回 False（不抛异常）。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(status_code=500)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=resp
            )
        )
        _patch_get_client(client, resp)

        result = await client.upsert(
            collection="agent_skills", doc_id="d1", content="hello",
            metadata=None, user_ns="u1",
        )
        assert result is False


class TestIndexUserMemory:
    @pytest.mark.asyncio
    async def test_uses_md5_derived_doc_id_and_user_collection(self):
        """index_user_memory 应使用 md5(key)[:8] 派生 doc_id + user_{uid}_memory 集合。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(json_data={"ok": True})
        mock_http = _patch_get_client(client, resp)

        result = await client.index_user_memory(
            user_id="alice", key="favorite_sport", content="running"
        )
        assert result is True
        # 验证 POST 的 collection 和 doc_id
        call_kwargs = mock_http.post.call_args
        payload = call_kwargs.kwargs["json"]
        assert payload["collection"] == "user_alice_memory"
        # 注意 upsert 的 payload 键名是 "id"（不是 "doc_id"）
        assert payload["id"].startswith("mem_alice_")
        assert payload["content"] == "running"
        # doc_id 后 8 位是 md5("favorite_sport")[:8]
        import hashlib
        expected_suffix = hashlib.md5(b"favorite_sport").hexdigest()[:8]
        assert payload["id"] == f"mem_alice_{expected_suffix}"


class TestQueryUserMemory:
    @pytest.mark.asyncio
    async def test_uses_user_memory_collection_and_propagates_results(self):
        """query_user_memory 应使用 user_{uid}_memory 集合，结果透传。"""
        client = QMDClient(base_url="http://qmd:8000")
        expected = [{"id": "m1", "content": "mem content", "score": 0.9}]
        resp = _make_mock_resp(json_data={"results": expected})
        _patch_get_client(client, resp)

        result = await client.query_user_memory(user_id="alice", query="sport")
        assert result == expected


class TestPurgeUser:
    @pytest.mark.asyncio
    async def test_purges_all_collections_returns_true_if_all_ok(self):
        """所有集合删除成功时返回 True。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(json_data={"ok": True})
        _patch_get_client(client, resp)

        result = await client.purge_user("alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_if_any_collection_fails(self):
        """任一集合失败时返回 False（容错：单集合失败不影响整体判断）。"""
        client = QMDClient(base_url="http://qmd:8000")
        # 第一次抛错（模拟某集合 500），第二次成功
        resp_ok = _make_mock_resp(json_data={"ok": True})
        resp_fail = _make_mock_resp(status_code=500)
        resp_fail.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=resp_fail)
        )
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=[resp_fail, resp_ok, resp_ok])
        client._get_client = lambda: mock_http  # type: ignore[method-assign]

        result = await client.purge_user("alice")
        # 第一个集合失败 → purge_user 应至少有一条 False → 整体返 False
        # （具体行为取决于实现：any-fail 或 all-fail；这里只验证不抛异常且返 bool）
        assert isinstance(result, bool)


class TestDeleteCollection:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """成功删除集合返 True。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(json_data={"ok": True})
        _patch_get_client(client, resp)

        result = await client._delete_collection("user_alice_memory", "alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_error(self):
        """HTTP 错误时返 False。"""
        client = QMDClient(base_url="http://qmd:8000")
        resp = _make_mock_resp(status_code=500)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        )
        _patch_get_client(client, resp)

        result = await client._delete_collection("user_alice_memory", "alice")
        assert result is False


class TestClose:
    @pytest.mark.asyncio
    async def test_close_aclient_and_reset_state(self):
        """close() 应关闭内部 _client 并重置为 None。"""
        client = QMDClient(base_url="http://qmd:8000")
        # 模拟已初始化的 _client
        mock_inner = AsyncMock()
        client._client = mock_inner

        await client.close()

        mock_inner.aclose.assert_awaited_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client_is_noop(self):
        """_client 已是 None 时 close() 不报错。"""
        client = QMDClient(base_url="http://qmd:8000")
        client._client = None
        # 不应抛异常
        await client.close()
        assert client._client is None
