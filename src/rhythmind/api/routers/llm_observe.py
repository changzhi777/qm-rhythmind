"""
api/routers/llm_observe.py — LLM 观测 API 路由

提供 LLM 调用指标、Trace 列表、成本统计、优化建议和 AI 深度分析。
数据直查 Langfuse v2 PG 数据库（只读）。

Langfuse v2 observations 表结构：
  - level: 'DEFAULT' | 'WARNING' | 'ERROR'
  - start_time, end_time → 计算延迟
  - total_tokens, prompt_tokens, completion_tokens
  - total_cost, input_cost, output_cost
  - modelParameters (jsonb)
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from rhythmind.api.deps import CurrentUserId
from rhythmind.observability.suggestion_engine import (
    ModelMetrics,
    generate_suggestions,
)

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


class SuggestionResponse(BaseModel):
    suggestions: list[dict[str, Any]]


class AnalyzeRequest(BaseModel):
    days: int = 7


# ── PG 直查辅助 ────────────────────────────────────────────────────────

_pg_engine: Any = None


def _get_pg_engine() -> Any:  # noqa: ANN401
    from sqlalchemy.ext.asyncio import create_async_engine

    from rhythmind.config import settings

    global _pg_engine
    if _pg_engine is not None:
        return _pg_engine

    db_url = settings.langfuse_db_url
    if not db_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Langfuse 数据库未配置（LANGFUSE_DB_URL）",
        )

    _pg_engine = create_async_engine(db_url, pool_size=2, max_overflow=0)
    return _pg_engine


async def _query_pg(
    sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    engine = _get_pg_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params or {})
        columns = result.keys()
        return [dict(zip(columns, row, strict=False)) for row in result.fetchall()]


# ── GET /metrics ────────────────────────────────────────────────────────


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="LLM 调用汇总指标",
)
async def get_metrics(
    user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=90),
) -> MetricsResponse:
    rows = await _query_pg(
        """
        SELECT
            COUNT(*) as total_calls,
            COALESCE(
                SUM(CASE WHEN level != 'ERROR' THEN 1 ELSE 0 END), 0
            ) as success_calls,
            COALESCE(
                AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000), 0
            ) as avg_latency_ms,
            COALESCE(
                PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (end_time - start_time)) * 1000
                ), 0
            ) as p95_latency_ms,
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

    summary = rows[0] if rows else {}
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
    )


# ── GET /traces ────────────────────────────────────────────────────────


@router.get(
    "/traces",
    summary="Trace 列表",
)
async def list_traces(
    user_id: CurrentUserId,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    model: str | None = Query(None),
) -> list[TraceItem]:
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
            o.created_at::text
        FROM observations o
        JOIN traces t ON t.id = o.trace_id
        {where}
        ORDER BY o.created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        qp,
    )
    return [TraceItem(**r) for r in rows]


# ── GET /traces/{trace_id} ─────────────────────────────────────────────


@router.get(
    "/traces/{trace_id}",
    summary="Trace 详情",
)
async def get_trace_detail(
    trace_id: str,
    user_id: CurrentUserId,
) -> TraceDetail:
    rows = await _query_pg(
        """
        SELECT
            o.id::text,
            o.name,
            o.input,
            o.output,
            o.model,
            COALESCE(o."modelParameters", '{{}}') as model_params,
            json_build_object(
                'prompt', o.prompt_tokens,
                'completion', o.completion_tokens,
                'total', o.total_tokens
            ) as tokens,
            json_build_object(
                'input', o.input_cost,
                'output', o.output_cost,
                'total', o.total_cost
            ) as cost,
            EXTRACT(EPOCH FROM (o.end_time - o.start_time)) * 1000 as latency_ms,
            COALESCE(o.metadata, '{{}}') as metadata,
            o.created_at::text
        FROM observations o
        WHERE o.id::text = :tid AND o.type = 'GENERATION'
        """,
        {"tid": trace_id},
    )
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trace 不存在",
        )
    return TraceDetail(**rows[0])


# ── GET /suggestions ───────────────────────────────────────────────────


@router.get(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="规则引擎优化建议",
)
async def get_suggestions(
    user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=30),
) -> SuggestionResponse:
    rows = await _query_pg(
        """
        SELECT
            model,
            COUNT(*) as total_calls,
            SUM(CASE WHEN level != 'ERROR' THEN 1 ELSE 0 END) as success_calls,
            AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000) as avg_latency_ms,
            COALESCE(
                PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (end_time - start_time)) * 1000
                ), 0
            ) as p95_latency_ms,
            SUM(total_tokens) as total_tokens,
            SUM(total_cost) as total_cost,
            CASE WHEN SUM(prompt_tokens) > 0
                THEN SUM(completion_tokens)::float / SUM(prompt_tokens)
                ELSE 0 END as output_input_ratio
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        """,
        {"days": days},
    )

    models = [
        ModelMetrics(
            model=r.get("model") or "unknown",
            total_calls=r.get("total_calls", 0) or 0,
            success_calls=r.get("success_calls", 0) or 0,
            avg_latency_ms=r.get("avg_latency_ms", 0) or 0,
            p95_latency_ms=r.get("p95_latency_ms", 0) or 0,
            total_tokens=r.get("total_tokens", 0) or 0,
            total_cost=r.get("total_cost", 0) or 0,
            output_input_ratio=r.get("output_input_ratio", 0) or 0,
        )
        for r in rows
    ]

    suggestions = generate_suggestions(models)
    return SuggestionResponse(
        suggestions=[
            {
                "title": s.title,
                "severity": s.severity,
                "detail": s.detail,
                "metric_key": s.metric_key,
                "current_value": s.current_value,
                "threshold": s.threshold,
            }
            for s in suggestions
        ],
    )


# ── POST /analyze ───────────────────────────────────────────────────────


@router.post(
    "/analyze",
    summary="LLM 深度分析（AI 优化报告）",
)
async def analyze_llm_usage(
    body: AnalyzeRequest,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    metrics_rows = await _query_pg(
        """
        SELECT
            model,
            COUNT(*) as calls,
            AVG(EXTRACT(EPOCH FROM (end_time - start_time)) * 1000) as avg_latency,
            SUM(total_tokens) as tokens,
            SUM(total_cost) as cost,
            SUM(CASE WHEN level = 'ERROR' THEN 1 ELSE 0 END) as errors
        FROM observations
        WHERE type = 'GENERATION'
          AND created_at >= NOW() - INTERVAL '1 day' * :days
        GROUP BY model
        ORDER BY calls DESC
        """,
        {"days": body.days},
    )

    if not metrics_rows:
        return {"status": "no_data", "report": "无 LLM 调用数据可供分析"}

    summary = json.dumps(metrics_rows, ensure_ascii=False, default=str)

    from rhythmind.config import settings

    prompt = f"""你是 LLM 运维专家。基于以下近 {body.days} 天的 LLM 调用统计数据，
生成一份优化报告（中文），包含：

1. 调用概况分析
2. 性能瓶颈识别
3. 成本优化建议
4. 具体行动建议（优先级排序）

统计数据：
{summary}

请用 Markdown 格式输出。"""

    from rhythmind.adapters.adapter_router import adapter_router

    try:
        report = await adapter_router.chat(
            messages=[{"role": "user", "content": prompt}],
            model_spec=settings.model_primary_spec,
        )
        return {"status": "success", "report": report}
    except Exception as e:
        return {"status": "error", "report": f"分析失败: {e}"}
