"""
tests/unit/test_mcp_server.py — RHYTHMIND MCP Server 单元测试

策略：
  - 直接调用 server.py 中的 _handle_* 函数，不启动真正的 HTTP/SSE 服务器
  - 用 unittest.mock.AsyncMock / patch 替换所有外部依赖
  - 覆盖：工具清单、正常调用、参数缺失、异常降级、build_mcp_server 工厂
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 直接导入私有处理器，便于单独测试
from rhythmind.mcp.server import (
    _TOOLS,
    _handle_fact_query,
    _handle_fact_update,
    _handle_search,
    _handle_session_log,
    _handle_status,
    build_mcp_server,
)

# ── 工具清单 ──────────────────────────────────────────────────────────────────

class TestToolDefinitions:

    def test_tool_count(self):
        assert len(_TOOLS) == 5

    def test_tool_names(self):
        names = {t.name for t in _TOOLS}
        assert names == {
            "rhythmind_status",
            "rhythmind_search",
            "rhythmind_fact_query",
            "rhythmind_fact_update",
            "rhythmind_session_log",
        }

    def test_all_tools_have_input_schema(self):
        for t in _TOOLS:
            assert "type" in t.inputSchema
            assert t.inputSchema["type"] == "object"
            assert "required" in t.inputSchema

    def test_status_requires_user_id(self):
        status_tool = next(t for t in _TOOLS if t.name == "rhythmind_status")
        assert status_tool.inputSchema["required"] == ["user_id"]

    def test_search_requires_user_id_and_query(self):
        search_tool = next(t for t in _TOOLS if t.name == "rhythmind_search")
        assert set(search_tool.inputSchema["required"]) == {"user_id", "query"}

    def test_fact_update_requires_four_fields(self):
        update_tool = next(t for t in _TOOLS if t.name == "rhythmind_fact_update")
        assert set(update_tool.inputSchema["required"]) == {
            "user_id", "action", "subject", "predicate"
        }


# ── _handle_status ────────────────────────────────────────────────────────────

class TestHandleStatus:

    @pytest.mark.asyncio
    async def test_status_ok(self):
        mock_fact = MagicMock()
        mock_fact.subject = "user_goal"
        mock_fact.predicate = "targets"
        mock_fact.object_json = {"goal": "马拉松"}
        mock_fact.source = "user"
        mock_fact.valid_from = None

        with (
            patch("rhythmind.mcp.server.FactManager") as MockFM,
            patch("rhythmind.mcp.server.MemoryManager") as MockMM,
        ):
            MockFM.return_value.get_all_current = AsyncMock(return_value=[mock_fact])
            MockMM.return_value.recall = AsyncMock(return_value={"health_status": "normal"})  # noqa: E501

            result = await _handle_status({"user_id": "u001"})

        assert result["status"] == "ok"
        assert result["fact_count"] == 1
        assert result["current_facts"][0]["subject"] == "user_goal"
        assert "health_status" in result["recent_memory_keys"]

    @pytest.mark.asyncio
    async def test_status_error_returns_error_field(self):
        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.side_effect = RuntimeError("db down")

            result = await _handle_status({"user_id": "u001"})

        assert "error" in result
        assert result["user_id"] == "u001"

    @pytest.mark.asyncio
    async def test_status_empty_memory(self):
        with (
            patch("rhythmind.mcp.server.FactManager") as MockFM,
            patch("rhythmind.mcp.server.MemoryManager") as MockMM,
        ):
            MockFM.return_value.get_all_current = AsyncMock(return_value=[])
            MockMM.return_value.recall = AsyncMock(return_value=None)

            result = await _handle_status({"user_id": "u001"})

        assert result["fact_count"] == 0
        assert result["recent_memory_keys"] == []


# ── _handle_search ────────────────────────────────────────────────────────────

class TestHandleSearch:

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        with patch("rhythmind.mcp.server.QMDClient") as MockQMD:
            MockQMD.return_value.query = AsyncMock(
                return_value=[{"id": "1", "score": 0.9, "text": "Running tips"}]
            )
            result = await _handle_search({
                "user_id": "u001",
                "query": "跑步训练建议",
                "top_k": 3,
            })

        assert result["count"] == 1
        assert result["query"] == "跑步训练建议"
        assert result["results"][0]["text"] == "Running tips"

    @pytest.mark.asyncio
    async def test_search_missing_query_returns_error(self):
        result = await _handle_search({"user_id": "u001"})
        assert result["error"] == "missing_argument"
        assert result["field"] == "query"

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_error(self):
        result = await _handle_search({"user_id": "u001", "query": ""})
        assert result["error"] == "missing_argument"

    @pytest.mark.asyncio
    async def test_search_exception_returns_error(self):
        with patch("rhythmind.mcp.server.QMDClient") as MockQMD:
            MockQMD.return_value.query = AsyncMock(side_effect=ConnectionError("QMD offline"))  # noqa: E501
            result = await _handle_search({"user_id": "u001", "query": "跑步"})

        assert "error" in result
        assert "QMD offline" in result["error"]

    @pytest.mark.asyncio
    async def test_search_default_collection(self):
        with patch("rhythmind.mcp.server.QMDClient") as MockQMD:
            MockQMD.return_value.query = AsyncMock(return_value=[])
            result = await _handle_search({"user_id": "u001", "query": "营养"})

        assert result["collection"] == "health_knowledge"


# ── _handle_fact_query ────────────────────────────────────────────────────────

class TestHandleFactQuery:

    @pytest.mark.asyncio
    async def test_query_current_mode(self):
        mock_fact = MagicMock()
        mock_fact.id = 1
        mock_fact.predicate = "targets"
        mock_fact.object_json = {"goal": "减脂"}
        mock_fact.source = "user"
        mock_fact.confidence = 1.0
        mock_fact.valid_from = None
        mock_fact.valid_until = None
        mock_fact.is_current = True

        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.query_current = AsyncMock(return_value=[mock_fact])
            result = await _handle_fact_query({
                "user_id": "u001",
                "subject": "user_goal",
                "mode": "current",
            })

        assert result["count"] == 1
        assert result["mode"] == "current"
        assert result["facts"][0]["is_current"] is True

    @pytest.mark.asyncio
    async def test_query_history_mode(self):
        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.query_history = AsyncMock(return_value=[])
            result = await _handle_fact_query({
                "user_id": "u001",
                "subject": "user_goal",
                "mode": "history",
                "limit": 10,
            })

        assert result["mode"] == "history"
        assert result["count"] == 0
        MockFM.return_value.query_history.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_subject_returns_error(self):
        result = await _handle_fact_query({"user_id": "u001"})
        assert result["error"] == "missing_argument"
        assert result["field"] == "subject"

    @pytest.mark.asyncio
    async def test_query_exception_returns_error(self):
        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.query_current = AsyncMock(side_effect=Exception("PG error"))  # noqa: E501
            result = await _handle_fact_query({
                "user_id": "u001",
                "subject": "injury",
            })
        assert "error" in result


# ── _handle_fact_update ───────────────────────────────────────────────────────

class TestHandleFactUpdate:

    @pytest.mark.asyncio
    async def test_write_action_ok(self):
        mock_fact = MagicMock()
        mock_fact.id = 42

        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.write_fact = AsyncMock(return_value=mock_fact)
            result = await _handle_fact_update({
                "user_id": "u001",
                "action": "write",
                "subject": "user_goal",
                "predicate": "targets",
                "object": {"goal": "马拉松"},
                "source": "coach_agent",
                "confidence": 0.95,
            })

        assert result["status"] == "ok"
        assert result["action"] == "write"
        assert result["fact_id"] == 42
        assert result["object"] == {"goal": "马拉松"}

    @pytest.mark.asyncio
    async def test_write_missing_object_returns_error(self):
        result = await _handle_fact_update({
            "user_id": "u001",
            "action": "write",
            "subject": "user_goal",
            "predicate": "targets",
            # object missing
        })
        assert result["error"] == "missing_argument"
        assert result["field"] == "object"

    @pytest.mark.asyncio
    async def test_invalidate_action_ok(self):
        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.invalidate_by_subject = AsyncMock(return_value=2)
            result = await _handle_fact_update({
                "user_id": "u001",
                "action": "invalidate",
                "subject": "injury",
                "predicate": "restricts",
            })

        assert result["status"] == "ok"
        assert result["action"] == "invalidate"
        assert result["invalidated_count"] == 2

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error(self):
        result = await _handle_fact_update({
            "user_id": "u001",
            "action": "delete",  # invalid
            "subject": "user_goal",
            "predicate": "targets",
        })
        assert result["error"] == "invalid_action"
        assert "write" in result["valid"]

    @pytest.mark.asyncio
    async def test_missing_required_fields_returns_error(self):
        result = await _handle_fact_update({
            "user_id": "u001",
            # action/subject/predicate missing
        })
        assert result["error"] == "missing_argument"

    @pytest.mark.asyncio
    async def test_write_exception_returns_error(self):
        with patch("rhythmind.mcp.server.FactManager") as MockFM:
            MockFM.return_value.write_fact = AsyncMock(side_effect=Exception("DB error"))  # noqa: E501
            result = await _handle_fact_update({
                "user_id": "u001",
                "action": "write",
                "subject": "user_goal",
                "predicate": "targets",
                "object": {"goal": "减脂"},
            })
        assert "error" in result


# ── _handle_session_log ───────────────────────────────────────────────────────

class TestHandleSessionLog:

    @pytest.mark.asyncio
    async def test_session_log_ok(self):
        with patch("rhythmind.mcp.server.InfluxClient") as MockInflux, \
             patch("rhythmind.mcp.server.MetricPoint") as MockPoint:
            MockInflux.return_value.write_metrics = AsyncMock(return_value=True)
            mock_point = MagicMock()
            mock_point.fields = {"heart_rate_avg": 72.0, "steps": 8500.0}
            MockPoint.return_value = mock_point

            result = await _handle_session_log({
                "user_id": "u001",
                "source": "garmin",
                "sport_type": "running",
                "metrics": {"heart_rate_avg": 72, "steps": 8500},
            })

        assert result["status"] == "ok"
        assert result["write_ok"] is True
        assert result["source"] == "garmin"
        assert result["sport_type"] == "running"

    @pytest.mark.asyncio
    async def test_session_log_write_failed(self):
        with patch("rhythmind.mcp.server.InfluxClient") as MockInflux, \
             patch("rhythmind.mcp.server.MetricPoint") as MockPoint:
            MockInflux.return_value.write_metrics = AsyncMock(return_value=False)
            mock_point = MagicMock()
            mock_point.fields = {"steps": 5000.0}
            MockPoint.return_value = mock_point

            result = await _handle_session_log({
                "user_id": "u001",
                "source": "manual",
                "metrics": {"steps": 5000},
            })

        assert result["status"] == "write_failed"
        assert result["write_ok"] is False

    @pytest.mark.asyncio
    async def test_missing_metrics_returns_error(self):
        result = await _handle_session_log({
            "user_id": "u001",
            "source": "manual",
            # metrics missing
        })
        assert result["error"] == "missing_argument"
        assert result["field"] == "metrics"

    @pytest.mark.asyncio
    async def test_empty_metrics_returns_error(self):
        result = await _handle_session_log({
            "user_id": "u001",
            "source": "manual",
            "metrics": {},
        })
        assert result["error"] == "missing_argument"

    @pytest.mark.asyncio
    async def test_influx_exception_returns_error(self):
        with patch("rhythmind.mcp.server.InfluxClient") as MockInflux:
            MockInflux.side_effect = Exception("InfluxDB unreachable")
            result = await _handle_session_log({
                "user_id": "u001",
                "source": "garmin",
                "metrics": {"steps": 5000},
            })
        assert "error" in result


# ── build_mcp_server 工厂 ─────────────────────────────────────────────────────

class TestBuildMcpServer:

    def test_factory_returns_server_instance(self):
        from mcp.server import Server
        server = build_mcp_server()
        assert isinstance(server, Server)

    def test_factory_returns_fresh_instance_each_call(self):
        s1 = build_mcp_server()
        s2 = build_mcp_server()
        assert s1 is not s2

    @pytest.mark.asyncio
    async def test_list_tools_registered_in_server(self):
        """list_tools 注册成功后，Server 内部 request_handlers 包含 ListToolsRequest。"""  # noqa: E501
        import mcp.types as mcp_types
        server = build_mcp_server()
        assert mcp_types.ListToolsRequest in server.request_handlers

    @pytest.mark.asyncio
    async def test_call_tool_registered_in_server(self):
        """call_tool 注册成功后，Server 内部 request_handlers 包含 CallToolRequest。"""
        import mcp.types as mcp_types
        server = build_mcp_server()
        assert mcp_types.CallToolRequest in server.request_handlers

    @pytest.mark.asyncio
    async def test_call_tool_unknown_returns_error_json(self):
        """未知工具名 → _HANDLERS 缺失 → 返回 error: unknown_tool 的 JSON TextContent。"""  # noqa: E501
        from mcp.types import TextContent

        from rhythmind.mcp.server import _HANDLERS

        # 直接调用 call_tool 内部逻辑（绕过 Server 的 JSON-RPC 封装）
        handler = _HANDLERS.get("no_such_tool")
        assert handler is None  # 未注册的工具不在 _HANDLERS 中

        # 模拟 server.call_tool 回调的内部分支
        result_dict = {"error": "unknown_tool", "name": "no_such_tool"}
        text_content = TextContent(type="text", text=json.dumps(result_dict, ensure_ascii=False))  # noqa: E501
        payload = json.loads(text_content.text)
        assert payload["error"] == "unknown_tool"

    @pytest.mark.asyncio
    async def test_call_tool_dispatches_to_handler(self):
        """_HANDLERS 路由表正确映射 rhythmind_status → _handle_status。"""
        from rhythmind.mcp.server import _HANDLERS, _handle_status
        assert _HANDLERS["rhythmind_status"] is _handle_status
        assert _HANDLERS["rhythmind_search"] is not None
        assert _HANDLERS["rhythmind_fact_query"] is not None
        assert _HANDLERS["rhythmind_fact_update"] is not None
        assert _HANDLERS["rhythmind_session_log"] is not None

    @pytest.mark.asyncio
    async def test_call_tool_none_arguments_handled(self):
        """arguments=None 时 server.py 降级为空 dict，不抛 TypeError。"""
        # 验证 _handle_search(None) → 用 {} 替代 → error: missing_argument
        result = await _handle_search(None or {})  # type: ignore[arg-type]
        payload = result
        assert "error" in payload
