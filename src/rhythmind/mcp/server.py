# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
mcp/server.py — RHYTHMIND MCP Server（5 个健康记忆工具）

参考 MemPalace 的 19-tool 设计理念，为 RHYTHMIND 实现 MCP 原生接入，
让任何 MCP 兼容客户端（Claude Code、Claude Desktop、企业微信 Bot 等）
无需适配层即可调用健康记忆查询与更新。

工具清单：
  rhythmind_status       — 用户健康概览（当前有效事实 + 近期记忆摘要）
  rhythmind_search       — 语义检索健康知识库（QMD 向量搜索）
  rhythmind_fact_query   — 时序知识图谱查询（当前/历史健康事实）
  rhythmind_fact_update  — 写入或过期健康事实（目标/伤病/基线等）
  rhythmind_session_log  — 训练会话日志写入（InfluxDB time-series）

认证约定：
  每个工具的 arguments 必须包含 user_id 字段。
  生产环境中由 FastAPI MCP router 在 SSE 握手阶段验证 JWT，
  此处 server.py 只做业务逻辑，不重复验证。

错误策略：
  业务异常 → 返回带 error 字段的 JSON TextContent，不抛出
  未知参数 → 返回 error: "missing_argument"
"""
from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

# ── 业务层依赖（模块级导入，便于 unittest.mock.patch 拦截）──────────────────────
# 使用 try/except 允许在纯测试环境下缺少部分依赖时仍可导入 server 模块
try:
    from rhythmind.core.memory import FactManager, MemoryManager
except ImportError:  # pragma: no cover
    FactManager = None  # type: ignore[assignment,misc]
    MemoryManager = None  # type: ignore[assignment,misc]

try:
    from rhythmind.core.qmd import QMDClient
except ImportError:  # pragma: no cover
    QMDClient = None  # type: ignore[assignment,misc]

try:
    from rhythmind.adapters.influx_client import InfluxClient, MetricPoint
except ImportError:  # pragma: no cover
    InfluxClient = None  # type: ignore[assignment,misc]
    MetricPoint = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ── 工具定义（inputSchema 使用 JSON Schema draft-07）──────────────────────────

_TOOLS: list[Tool] = [
    Tool(
        name="rhythmind_status",
        description=(
            "获取指定用户的健康概览：当前有效的健康事实（目标/伤病/基线）"
            "以及近期记忆摘要。适合 Agent 启动时调用，快速掌握用户状态。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "用户唯一标识符",
                },
            },
            "required": ["user_id"],
        },
    ),
    Tool(
        name="rhythmind_search",
        description=(
            "在健康知识库中进行语义检索（BM25 + 向量 + LLM 重排序）。"
            "适合查找运动健康建议、营养知识、训练技巧等通用知识。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string", "description": "用户 ID（用于个性化排序）"
                },
                "query": {
                    "type": "string", "description": "检索查询语句（中文/英文均可）"
                },
                "collection": {
                    "type": "string",
                    "description": "检索集合，默认 health_knowledge",
                    "default": "health_knowledge",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                    "default": 5,
                },
            },
            "required": ["user_id", "query"],
        },
    ),
    Tool(
        name="rhythmind_fact_query",
        description=(
            "查询用户的时序健康知识图谱。"
            "可查询当前有效事实（如：当前训练目标、当前伤病限制）"
            "或全部历史记录（含已过期，用于趋势分析）。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id":   {"type": "string", "description": "用户 ID"},
                "subject":   {
                    "type": "string",
                    "description": "查询主体，如 user_goal / injury / baseline",
                },
                "predicate": {
                    "type": "string",
                    "description": "关系谓词（可选），如 targets / restricts / heart_rate_avg",  # noqa: E501
                },
                "mode": {
                    "type": "string",
                    "enum": ["current", "history"],
                    "description": "current=仅当前有效，history=含历史，默认 current",
                    "default": "current",
                },
                "limit": {
                    "type": "integer",
                    "description": "历史模式最大返回条数，默认 20",
                    "default": 20,
                },
            },
            "required": ["user_id", "subject"],
        },
    ),
    Tool(
        name="rhythmind_fact_update",
        description=(
            "写入或过期用户的健康事实。"
            "写入时自动将同 subject+predicate 的旧有效记录标记过期，"
            "历史轨迹完整保留。"
            "典型场景：用户更换训练目标、记录新伤病、更新体能基线。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id":     {"type": "string", "description": "用户 ID"},
                "action": {
                    "type": "string",
                    "enum": ["write", "invalidate"],
                    "description": "write=写入新事实并过期旧值；invalidate=批量过期",
                },
                "subject":     {"type": "string", "description": "主体，如 user_goal / injury"},  # noqa: E501
                "predicate":   {"type": "string", "description": "谓词，如 targets / restricts"},  # noqa: E501
                "object":      {
                    "type": "object",
                    "description": "事实值（write 时必填），任意 JSON 结构",
                },
                "source":      {
                    "type": "string",
                    "description": "来源 Agent 名称，默认 mcp_client",
                    "default": "mcp_client",
                },
                "confidence":  {
                    "type": "number",
                    "description": "置信度 0-1，默认 1.0",
                    "default": 1.0,
                },
            },
            "required": ["user_id", "action", "subject", "predicate"],
        },
    ),
    Tool(
        name="rhythmind_session_log",
        description=(
            "将本次训练会话数据写入 InfluxDB 时序库。"
            "适合每次训练结束后调用，记录心率、距离、步数等指标，"
            "供 MetricsAgent 后续趋势分析使用。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "用户 ID"},
                "source":  {
                    "type": "string",
                    "description": "设备来源，如 garmin / apple / huawei / manual",  # noqa: E501
                },
                "sport_type": {
                    "type": "string",
                    "description": "运动类型，如 running / cycling / yoga，默认 general",  # noqa: E501
                    "default": "general",
                },
                "metrics": {
                    "type": "object",
                    "description": (
                        "本次训练指标，支持字段：heart_rate_avg, heart_rate_max, "
                        "steps, distance_km, calories, sleep_hours, hrv, "
                        "body_fat_pct, muscle_mass_kg, water_pct, visceral_fat"
                    ),
                },
            },
            "required": ["user_id", "source", "metrics"],
        },
    ),
]


# ── 工具处理器 ────────────────────────────────────────────────────────────────

async def _handle_status(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args["user_id"]
    try:
        fm = FactManager(user_id=user_id)
        mm = MemoryManager(user_id=user_id, agent="status")

        facts = await fm.get_all_current()
        recent_memory = await mm.recall("health_status")

        facts_summary = [
            {
                "subject": f.subject,
                "predicate": f.predicate,
                "object": f.object_json,
                "source": f.source,
                "since": f.valid_from.isoformat() if f.valid_from else None,
            }
            for f in facts
        ]

        return {
            "user_id": user_id,
            "current_facts": facts_summary,
            "fact_count": len(facts_summary),
            "recent_memory_keys": list(recent_memory.keys()) if recent_memory else [],  # type: ignore[attr-defined]
            "status": "ok",
        }
    except Exception as e:
        logger.error("rhythmind_status error: %s", e)
        return {"error": str(e), "user_id": user_id}


async def _handle_search(args: dict[str, Any]) -> dict[str, Any]:
    args.get("user_id", "")
    query = args.get("query", "")
    collection = args.get("collection", "health_knowledge")
    top_k = int(args.get("top_k", 5))

    if not query:
        return {"error": "missing_argument", "field": "query"}

    try:
        client = QMDClient()
        results = await client.query(collection=collection, query=query, top_k=top_k)
        return {
            "query": query,
            "collection": collection,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        logger.error("rhythmind_search error: %s", e)
        return {"error": str(e), "query": query}


async def _handle_fact_query(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", "")
    subject = args.get("subject", "")
    predicate = args.get("predicate")
    mode = args.get("mode", "current")
    limit = int(args.get("limit", 20))

    if not subject:
        return {"error": "missing_argument", "field": "subject"}

    try:
        fm = FactManager(user_id=user_id)

        if mode == "history":
            facts = await fm.query_history(subject, predicate, limit=limit)
        else:
            facts = await fm.query_current(subject, predicate)

        return {
            "user_id": user_id,
            "subject": subject,
            "predicate": predicate,
            "mode": mode,
            "facts": [
                {
                    "id": f.id,
                    "predicate": f.predicate,
                    "object": f.object_json,
                    "source": f.source,
                    "confidence": f.confidence,
                    "valid_from": f.valid_from.isoformat() if f.valid_from else None,
                    "valid_until": f.valid_until.isoformat() if f.valid_until else None,
                    "is_current": f.is_current,
                }
                for f in facts
            ],
            "count": len(facts),
        }
    except Exception as e:
        logger.error("rhythmind_fact_query error: %s", e)
        return {"error": str(e), "user_id": user_id}


async def _handle_fact_update(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", "")
    action = args.get("action", "")
    subject = args.get("subject", "")
    predicate = args.get("predicate", "")
    obj = args.get("object")
    source = args.get("source", "mcp_client")
    confidence = float(args.get("confidence", 1.0))

    if not all([user_id, action, subject, predicate]):
        return {
            "error": "missing_argument",
            "required": ["user_id", "action", "subject", "predicate"],
        }

    try:
        fm = FactManager(user_id=user_id)

        if action == "write":
            if obj is None:
                return {
                    "error": "missing_argument", "field": "object", "action": "write"
                }
            fact = await fm.write_fact(
                subject, predicate, obj, source=source, confidence=confidence
            )
            return {
                "action": "write",
                "fact_id": fact.id,
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "status": "ok",
            }

        elif action == "invalidate":
            count = await fm.invalidate_by_subject(subject, predicate or None)
            return {
                "action": "invalidate",
                "subject": subject,
                "predicate": predicate or None,
                "invalidated_count": count,
                "status": "ok",
            }

        else:
            return {"error": "invalid_action", "valid": ["write", "invalidate"]}

    except Exception as e:
        logger.error("rhythmind_fact_update error: %s", e)
        return {"error": str(e), "user_id": user_id}


async def _handle_session_log(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id", "")
    source = args.get("source", "manual")
    sport_type = args.get("sport_type", "general")
    metrics = args.get("metrics", {})

    if not metrics:
        return {"error": "missing_argument", "field": "metrics"}

    try:
        client = InfluxClient()
        point = MetricPoint(
            user_id=user_id,
            source=source,
            sport_type=sport_type,
            fields={k: float(v) for k, v in metrics.items() if v is not None},
        )
        write_ok = await client.write_metrics(point)
        return {
            "user_id": user_id,
            "write_ok": write_ok,
            "source": source,
            "sport_type": sport_type,
            "fields_written": list(point.fields.keys()),
            "status": "ok" if write_ok else "write_failed",
        }
    except Exception as e:
        logger.error("rhythmind_session_log error: %s", e)
        return {"error": str(e), "user_id": user_id}


# ── 路由表 ────────────────────────────────────────────────────────────────────

_HANDLERS = {
    "rhythmind_status":      _handle_status,
    "rhythmind_search":      _handle_search,
    "rhythmind_fact_query":  _handle_fact_query,
    "rhythmind_fact_update": _handle_fact_update,
    "rhythmind_session_log": _handle_session_log,
}


# ── Server 工厂（每次 SSE 连接创建独立实例）──────────────────────────────────

def build_mcp_server() -> Server:
    """
    构建并返回配置好的 MCP Server 实例。

    Server 是无状态的（所有状态在 DB/InfluxDB），可在多连接间复用。
    但为安全起见，SSE Router 每次连接调用此工厂，避免跨连接状态泄漏。
    """
    server = Server("rhythmind-health")

    @server.list_tools()  # type: ignore[no-untyped-call]
    async def list_tools() -> list[Tool]:
        return _TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = _HANDLERS.get(name)
        if handler is None:
            result = {"error": "unknown_tool", "name": name}
        else:
            result = await handler(arguments or {})

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server
