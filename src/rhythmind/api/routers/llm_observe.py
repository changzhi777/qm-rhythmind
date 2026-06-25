"""
api/routers/llm_observe.py — LLM 观测 API 路由 (双源查询 2026-06-25)

提供 LLM 调用指标、Trace 列表、成本统计、优化建议和 AI 深度分析。

数据源(双通道):
  1. 主源:Langfuse v2 PG (settings.langfuse_db_url) - 生产标准
  2. 兜底:本地 llm_call_log 表 - 本地开发/无 Langfuse 时使用

查询策略:
  - 优先查 Langfuse,失败/无配置/空结果时 fallback 到本地表
  - @observe_llm 装饰器始终写本地表,保证至少有数据

Langfuse v2 observations 表结构:
  - level: 'DEFAULT' | 'WARNING' | 'ERROR'
  - start_time, end_time → 计算延迟
  - total_tokens, prompt_tokens, completion_tokens
  - total_cost, input_cost, output_cost
  - modelParameters (jsonb)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from rhythmind.api.deps import CurrentUserId
from rhythmind.observability.suggestion_engine import (
    ModelMetrics,
    generate_suggestions,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm-observe", tags=["llm-observe"])


# ── 响应模型 ────────────────────────────────────────────────────────────


class MetricsResponse(BaseModel):
    total_calls: int
    success_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_tokens: int
    total_cost: float
    by_model: list[dict[str, Any]]
    by_day: list[dict[str, Any]]
    source: str = "langfuse"  # langfuse / local


class TraceItem(BaseModel):
    id: str
    name: str
    user_id: str | None
    model: str | None
    status: str
    latency_ms: float | None
    tokens: int
    cost: float
    created_at: str
    error_msg: str | None = None


class TraceDetail(BaseModel):
    id: str
    name: str
    input: Any
    output: Any
    model: str | None
    model_params: dict[str, Any]
    tokens: dict[str, int]
    cost: dict[str, float]
    latency_ms: float | None
    metadata: dict[str, Any]
    created_at: str
    error_msg: str | None = None


class SuggestionResponse(BaseModel):
    suggestions: list[dict[str, Any]]


class AnalyzeRequest(BaseModel):
    days: int = 7


# ── PG 直查辅助 (Langfuse) ────────────────────────────────────────────

_pg_engine: Any = None
_pg_unavailable: bool = False  # 标记 Langfuse DB 是否可用


def _get_pg_engine() -> Any:  # noqa: ANN401
    """获取 Langfuse PG 引擎,不可用时返回 None。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    from rhythmind.config import settings

    global _pg_engine, _pg_unavailable
    if _pg_unavailable:
        return None
    if _pg_engine is not None:
        return _pg_engine

    db_url = settings.langfuse_db_url
    if not db_url:
        _pg_unavailable = True
        return None

    _pg_engine = create_async_engine(db_url, pool_size=2, max_overflow=0)
    return _pg_engine


async def _query_pg(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """查 Langfuse PG,失败返回空(由调用方决定是否 fallback)。"""
    from sqlalchemy import text

    engine = _get_pg_engine()
    if engine is None:
        return []
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            columns = result.keys()
            return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
    except Exception as e:
        global _pg_unavailable
        _pg_unavailable = True
        logger.warning("langfuse_pg.query_failed fallback_to_local: %s", e)
        return []


# ── 本地表查询 (兜底) ────────────────────────────────────────────────


async def _query_local(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """查本地 llm_call_log 表。"""
    from sqlalchemy import text

    from rhythmind.core.memory.manager import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(sql), params or {})
            columns = result.keys()
            return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]
    except Exception as e:
        logger.warning("local_llm_log.query_failed: %s", e)
        return []


# ── GET /metrics ────────────────────────────────────────────────────────


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="LLM 调用汇总指标 (双源:Langfuse + 本地表)",
)
async def get_metrics(
    user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=90),
) -> MetricsResponse:
    """优先查 Langfuse,失败 fallback 到本地 llm_call_log。"""
    # ── 主源:Langfuse ──
    rows = await _query_pg(
        """
        SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(CASE WHEN level != 'ERROR' THEN 1 ELSE 0 END), 0) as success_calls,
            COALESCE(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000), 0) as avg_latency_ms,
            COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (end_time - start_time)) * 1000
            ), 0) as p95_latency_ms,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(total_cost), 0) as total_cost
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        """,
        {"days": days},
    )

    by_model = await _query_pg(
        """
        SELECT
            model,
            COUNT(*) as calls,
            AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000) as avg_latency_ms,
            SUM(total_tokens) as tokens,
            SUM(total_cost) as cost
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        ORDER BY calls DESC
        """,
        {"days": days},
    )

    by_day = await _query_pg(
        """
        SELECT
            DATE(created_at) as date,
            COUNT(*) as calls,
            AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000) as avg_latency_ms,
            SUM(total_tokens) as tokens,
            SUM(total_cost) as cost
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY DATE(created_at)
        ORDER BY date
        """,
        {"days": days},
    )

    if rows and rows[0].get("total_calls", 0) > 0:
        # Langfuse 有数据
        summary = rows[0]
        total = summary.get("total_calls", 0) or 0
        success = summary.get("success_calls", 0) or 0
        return MetricsResponse(
            total_calls=total,
            success_rate=round(success / total, 4) if total else 0,
            avg_latency_ms=round(summary.get("avg_latency_ms", 0) or 0, 1),
            p95_latency_ms=round(summary.get("p95_latency_ms", 0) or 0, 1),
            total_tokens=summary.get("total_tokens", 0) or 0,
            total_cost=round(summary.get("total_cost", 0) or 0, 6),
            by_model=by_model,
            by_day=by_day,
            source="langfuse",
        )

    # ── 兜底:本地表 ──
    logger.info("llm_observe.metrics: Langfuse empty/disabled, fallback to local")
    return await _get_metrics_local(days)


async def _get_metrics_local(days: int) -> MetricsResponse:
    """从本地 llm_call_log 表聚合指标。"""
    rows = await _query_local(
        """
        SELECT
            COUNT(*) as total_calls,
            COALESCE(SUM(CASE WHEN success = true THEN 1 ELSE 0 END), 0) as success_calls,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            COALESCE(
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms),
                0
            ) as p95_latency_ms,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(total_cost), 0) as total_cost
        FROM llm_call_log
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        """,
        {"days": days},
    )

    by_model = await _query_local(
        """
        SELECT
            model,
            COUNT(*) as calls,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            COALESCE(SUM(total_tokens), 0) as tokens,
            COALESCE(SUM(total_cost), 0) as cost
        FROM llm_call_log
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        ORDER BY calls DESC
        """,
        {"days": days},
    )

    by_day = await _query_local(
        """
        SELECT
            DATE(created_at) as date,
            COUNT(*) as calls,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            COALESCE(SUM(total_tokens), 0) as tokens,
            COALESCE(SUM(total_cost), 0) as cost
        FROM llm_call_log
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY DATE(created_at)
        ORDER BY date
        """,
        {"days": days},
    )

    summary = rows[0] if rows else {}
    total = summary.get("total_calls", 0) or 0
    success = summary.get("success_calls", 0) or 0

    return MetricsResponse(
        total_calls=total,
        success_rate=round(success / total, 4) if total else 0,
        avg_latency_ms=round(float(summary.get("avg_latency_ms", 0) or 0), 1),
        p95_latency_ms=round(float(summary.get("p95_latency_ms", 0) or 0), 1),
        total_tokens=summary.get("total_tokens", 0) or 0,
        total_cost=round(float(summary.get("total_cost", 0) or 0), 6),
        by_model=by_model,
        by_day=by_day,
        source="local",
    )


# ── GET /traces ────────────────────────────────────────────────────────


@router.get(
    "/traces",
    summary="Trace 列表 (双源)",
)
async def list_traces(
    user_id: CurrentUserId,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    model: str | None = Query(None),
) -> list[TraceItem]:
    """优先查 Langfuse,失败 fallback 到本地表。"""
    # 主源:Langfuse
    where = "WHERE o.type = 'GENERATION'"
    qp: dict[str, Any] = {"limit": limit, "offset": offset}
    if model:
        where += " AND o.model = :model"
        qp["model"] = model

    rows = await _query_pg(
        f"""
        SELECT
            o.id::text,
            o.name,
            t.user_id,
            o.model,
            CASE WHEN o.level = 'ERROR' THEN 'error' ELSE 'success' END as status,
            EXTRACT(EPOCH FROM (o.end_time - o.start_time)) * 1000 as latency_ms,
            COALESCE(o.total_tokens, 0) as tokens,
            COALESCE(o.total_cost, 0) as cost,
            o.created_at::text as created_at,
            o.error_message as error_msg
        FROM observations o
        JOIN traces t ON t.id = o.trace_id
        {where}
        ORDER BY o.created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        qp,
    )

    if rows:
        return [
            TraceItem(
                id=r["id"],
                name=r["name"] or "",
                user_id=r["user_id"],
                model=r["model"],
                status=r["status"],
                latency_ms=float(r["latency_ms"]) if r["latency_ms"] else None,
                tokens=int(r["tokens"] or 0),
                cost=float(r["cost"] or 0),
                created_at=str(r["created_at"]),
                error_msg=r.get("error_msg"),
            )
            for r in rows
        ]

    # 兜底:本地表
    logger.info("llm_observe.traces: Langfuse empty/disabled, fallback to local")
    local_qp: dict[str, Any] = {"limit": limit, "offset": offset}
    local_where = "WHERE 1=1"
    if model:
        local_where += " AND model = :model"
        local_qp["model"] = model

    rows = await _query_local(
        f"""
        SELECT
            id::text,
            agent || '.' || model as name,
            user_id,
            model,
            CASE WHEN success = false THEN 'error' ELSE 'success' END as status,
            latency_ms,
            total_tokens as tokens,
            total_cost as cost,
            created_at::text as created_at,
            error_msg
        FROM llm_call_log
        {local_where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        local_qp,
    )
    return [
        TraceItem(
            id=r["id"],
            name=r["name"] or "",
            user_id=r["user_id"],
            model=r["model"],
            status=r["status"],
            latency_ms=float(r["latency_ms"]) if r["latency_ms"] else None,
            tokens=int(r["tokens"] or 0),
            cost=float(r["cost"] or 0),
            created_at=str(r["created_at"]),
            error_msg=r.get("error_msg"),
        )
        for r in rows
    ]


# ── GET /traces/{id} ──────────────────────────────────────────────────


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetail,
    summary="Trace 详情 (双源)",
)
async def get_trace_detail(
    trace_id: str,
    user_id: CurrentUserId,
) -> TraceDetail:
    """优先查 Langfuse,失败 fallback 到本地。"""
    # 主源:Langfuse
    rows = await _query_pg(
        """
        SELECT
            o.id::text,
            o.name,
            o.input,
            o.output,
            o.model,
            o.model_parameters as model_params,
            jsonb_build_object(
                'input', COALESCE(o.prompt_tokens, 0),
                'output', COALESCE(o.completion_tokens, 0),
                'total', COALESCE(o.total_tokens, 0)
            ) as tokens,
            jsonb_build_object(
                'input', COALESCE(o.input_cost, 0),
                'output', COALESCE(o.output_cost, 0),
                'total', COALESCE(o.total_cost, 0)
            ) as cost,
            EXTRACT(EPOCH FROM (o.end_time - o.start_time)) * 1000 as latency_ms,
            t.metadata,
            o.created_at::text,
            o.error_message
        FROM observations o
        JOIN traces t ON t.id = o.trace_id
        WHERE o.id::text = :trace_id
        LIMIT 1
        """,
        {"trace_id": trace_id},
    )

    if rows:
        r = rows[0]
        return TraceDetail(
            id=r["id"],
            name=r["name"] or "",
            input=_safe_parse(r.get("input")),
            output=_safe_parse(r.get("output")),
            model=r["model"],
            model_params=r.get("model_params") or {},
            tokens=r.get("tokens") or {},
            cost=r.get("cost") or {},
            latency_ms=float(r["latency_ms"]) if r["latency_ms"] else None,
            metadata=r.get("metadata") or {},
            created_at=str(r["created_at"]),
            error_msg=r.get("error_message"),
        )

    # 兜底:本地表
    logger.info("llm_observe.trace_detail: Langfuse empty/disabled, fallback to local")
    rows = await _query_local(
        """
        SELECT
            id::text,
            agent || '.' || model as name,
            agent as input,
            model as output,
            model,
            model as model_params,
            jsonb_build_object('total', total_tokens) as tokens,
            jsonb_build_object('total', total_cost) as cost,
            latency_ms,
            jsonb_build_object('agent', agent) as metadata,
            created_at::text,
            error_msg,
            success
        FROM llm_call_log
        WHERE id::text = :trace_id
        LIMIT 1
        """,
        {"trace_id": trace_id},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found")
    r = rows[0]
    return TraceDetail(
        id=r["id"],
        name=r["name"] or "",
        input=r.get("input"),
        output=r.get("output"),
        model=r["model"],
        model_params={},
        tokens=r.get("tokens") or {},
        cost=r.get("cost") or {},
        latency_ms=float(r["latency_ms"]) if r["latency_ms"] else None,
        metadata=r.get("metadata") or {},
        created_at=str(r["created_at"]),
        error_msg=r.get("error_msg"),
    )


def _safe_parse(val: Any) -> Any:
    """安全解析 Langfuse JSON 字段。"""
    if val is None:
        return None
    if isinstance(val, (dict, list, int, float, bool, str)):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return str(val)


# ── GET /suggestions ───────────────────────────────────────────────────


@router.get(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="规则引擎建议 (双源)",
)
async def get_suggestions(
    user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=90),
) -> SuggestionResponse:
    """基于模型分布生成优化建议,使用当前数据源(Langfuse 或本地)。"""
    # 优先用 Langfuse 数据
    by_model_pg = await _query_pg(
        """
        SELECT
            model,
            COUNT(*) as total_calls,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(total_cost), 0) as total_cost,
            COALESCE(AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000), 0) as avg_latency_ms,
            COALESCE(
                SUM(CASE WHEN level = 'ERROR' THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0),
                0
            ) as error_rate
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        """,
        {"days": days},
    )

    if by_model_pg:
        metrics_list = [
            ModelMetrics(
                model=m["model"] or "unknown",
                total_calls=int(m["total_calls"] or 0),
                success_calls=int(m.get("success_calls") or m["total_calls"] or 0),
                avg_latency_ms=float(m["avg_latency_ms"] or 0),
                p95_latency_ms=0.0,
                total_tokens=int(m["total_tokens"] or 0),
                total_cost=float(m["total_cost"] or 0),
                output_input_ratio=0.0,
            )
            for m in by_model_pg
        ]
    else:
        # 兜底:本地表
        logger.info("llm_observe.suggestions: Langfuse empty/disabled, fallback to local")
        by_model_local = await _query_local(
            """
            SELECT
                model,
                COUNT(*) as total_calls,
                COALESCE(SUM(CASE WHEN success = true THEN 1 ELSE 0 END), 0) as success_calls,
                COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(total_cost), 0) as total_cost
            FROM llm_call_log
            WHERE created_at >= NOW() - INTERVAL '1 day' * :days
            GROUP BY model
            """,
            {"days": days},
        )
        metrics_list = [
            ModelMetrics(
                model=m["model"] or "unknown",
                total_calls=int(m["total_calls"] or 0),
                success_calls=int(m["success_calls"] or 0),
                avg_latency_ms=float(m["avg_latency_ms"] or 0),
                p95_latency_ms=0.0,
                total_tokens=int(m["total_tokens"] or 0),
                total_cost=float(m["total_cost"] or 0),
                output_input_ratio=0.0,
            )
            for m in by_model_local
        ]

    suggestions = generate_suggestions(metrics_list)
    return SuggestionResponse(
        suggestions=[s.__dict__ for s in suggestions],
    )


# ── POST /analyze ──────────────────────────────────────────────────────


@router.post(
    "/analyze",
    summary="AI 深度分析报告 (用主模型生成)",
)
async def analyze(
    body: AnalyzeRequest,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """用主模型生成 LLM 运维分析报告(基于最近 N 天数据)。"""
    from rhythmind.adapters.adapter_router import adapter_router
    from rhythmind.config import settings

    # 用本地表(保证总能用)
    by_model = await _query_local(
        """
        SELECT
            model,
            COUNT(*) as calls,
            COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(total_cost), 0) as total_cost
        FROM llm_call_log
        WHERE created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        ORDER BY calls DESC
        """,
        {"days": body.days},
    )

    if not by_model:
        return {
            "status": "ok",
            "report": "暂无 LLM 调用数据。请先在 Chat 页面发起一次对话。",
            "models": [],
        }

    summary = "\n".join(
        f"- {m['model']}: {m['calls']} 次调用, 平均 {m['avg_latency_ms']:.0f}ms, "
        f"{m['total_tokens']} tokens, ${m['total_cost']:.4f}"
        for m in by_model
    )

    prompt = f"""你是 LLM 运维专家。基于以下近 {body.days} 天的 LLM 调用统计数据,
生成一份优化报告(中文),包含:

1. 调用概况分析
2. 性能瓶颈识别
3. 成本优化建议
4. 具体行动建议(优先级排序)

统计数据:
{summary}

请用 Markdown 格式输出。"""

    try:
        report = await adapter_router.chat(
            messages=[{"role": "user", "content": prompt}],
            model_spec=settings.model_primary_spec,
        )
        return {"status": "success", "report": report, "models": [m["model"] for m in by_model]}
    except Exception as e:
        return {"status": "error", "report": f"分析失败: {e}", "models": []}
