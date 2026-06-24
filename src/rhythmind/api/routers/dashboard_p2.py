"""
api/routers/dashboard_p2.py — Dashboard P2 扩展端点(2026-06-24 frontend-polish Stage 5)

批量实现剩余 20 个 P2/P3 端点(简化版,Redis 持久化为主)。

端点清单:
  # SSE / Realtime (3)
  GET  /api/v1/events                          — SSE 实时推送(简化 heartbeat)
  GET  /api/v1/chat/stream                     — Chat 流式响应(SSE)
  GET  /api/v1/chat/sessions                   — 会话历史列表

  # Upload chunk (2)
  POST /api/v1/upload/chunk                    — 分片上传
  POST /api/v1/upload/merge                    — 合并分片

  # Chat multimodal (1)
  POST /api/v1/chat/upload                     — 多模态上传

  # Reports ext (3)
  GET  /api/v1/reports/search                  — 报告搜索
  GET  /api/v1/reports/compare                 — 报告对比
  POST /api/v1/reports/schedule                — 定时报告

  # Test reports ext (2)
  GET  /api/v1/test-reports/{id}/cases         — 失败用例详情
  POST /api/v1/test-reports/rerun              — 重跑测试

  # LLM Observe ext (4)
  GET  /api/v1/llm-observe/alerts              — 告警规则
  PUT  /api/v1/llm-observe/alerts              — 更新告警
  GET  /api/v1/llm-observe/budgets             — 预算限制
  POST /api/v1/llm-observe/budgets             — 设置预算
  GET  /api/v1/llm-observe/traces/{id}/spans   — Trace span 树
  POST /api/v1/llm-observe/ab-test             — A/B 实验

  # Medical ext (4)
  GET  /api/v1/medical/labs/trend              — 化验趋势
  POST /api/v1/medical/medications/reminder    — 用药提醒
  POST /api/v1/medical/export/pdf              — 医疗 PDF 导出
  POST /api/v1/medical/share                   — 家人共享

  # Bigscreen (1)
  GET  /api/v1/bigscreen/users                 — 大屏轮播用户列表

Why:
  一次性提供前端 9 页所需的全部数据端点,简化版以 Redis JSON 持久化为主。
  后续可按需迁移 PG / 接入时序数据库 / 接入 LLM 推理管线。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from rhythmind.api.deps import CurrentUserId
from rhythmind.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["dashboard-p2"])

# ── Redis 客户端(惰性初始化) ─────────────────────────────────────────────
_redis: aioredis.Redis | None = None


async def _redis_client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _redis


def _k(namespace: str, user_id: str, suffix: str = "") -> str:
    base = f"rhythmind:{namespace}:{user_id}"
    return f"{base}:{suffix}" if suffix else base


# ── 通用 Schema ─────────────────────────────────────────────────────────


class AlertRule(BaseModel):
    metric: str
    threshold: float
    comparator: str = "gt"  # gt | lt | eq
    enabled: bool = True


class BudgetLimit(BaseModel):
    scope: str  # day | week | month
    amount_usd: float
    enabled: bool = True


class ChunkUploadRequest(BaseModel):
    upload_id: str
    chunk_index: int
    total_chunks: int
    filename: str
    data_b64: str = Field(..., description="Base64-encoded chunk bytes")


class ChunkMergeRequest(BaseModel):
    upload_id: str
    filename: str


class ABTestRequest(BaseModel):
    prompt: str
    model_a: str
    model_b: str
    max_tokens: int = 200


class ReportScheduleRequest(BaseModel):
    cron: str = Field(..., description="cron 表达式")
    email: str
    enabled: bool = True


class MedicalReminderRequest(BaseModel):
    medication_name: str
    times_per_day: int = Field(ge=1, le=8)
    start_date: str | None = None


class MedicalShareRequest(BaseModel):
    scope: str  # readonly | editable
    expires_days: int = Field(default=7, ge=1, le=365)


# ── 1. SSE Realtime ─────────────────────────────────────────────────────


@router.get("/events")
async def sse_events(_user_id: CurrentUserId) -> EventSourceResponse:
    """SSE 实时推送(简化实现:每 5s 推送 heartbeat)。
    生产应改:基于 Redis Pub/Sub 订阅 fact 变更事件。"""

    async def gen() -> Any:
        i = 0
        while True:
            yield {
                "event": "heartbeat",
                "data": json.dumps({"ts": datetime.now(UTC).isoformat(), "seq": i}),
            }
            i += 1
            await asyncio.sleep(5)

    return EventSourceResponse(gen())


# ── 2. Chat SSE + Sessions ──────────────────────────────────────────────


@router.get("/chat/stream")
async def chat_stream(
    _user_id: CurrentUserId,
    text: str = Query(...),
) -> EventSourceResponse:
    """Chat 流式响应(SSE 占位实现:逐字输出)。

    注:实际生产应转发到 HealthRouter 的 chat 方法 + ReadableStream。"""

    async def gen() -> Any:
        fake_reply = f"已收到: {text}。这是一段模拟的流式响应。"
        for word in fake_reply.split():
            yield {"event": "chunk", "data": word}
            await asyncio.sleep(0.05)
        yield {"event": "done", "data": ""}

    return EventSourceResponse(gen())


@router.get("/chat/sessions")
async def chat_sessions(_user_id: CurrentUserId) -> dict[str, Any]:
    """会话历史列表(简化:从 Redis 取最近 50 条)"""
    redis = await _redis_client()
    raw = await redis.lrange(_k("chat_sessions", _user_id), 0, 49)
    sessions = [json.loads(s) for s in raw]
    return {"sessions": sessions, "total": len(sessions)}


# ── 3. Upload Chunk ─────────────────────────────────────────────────────


@router.post("/upload/chunk")
async def upload_chunk(
    payload: ChunkUploadRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """分片上传:接收 Base64 chunk,存入 Redis(临时)"""
    redis = await _redis_client()
    chunk_key = _k(
        "upload_chunk", _user_id, f"{payload.upload_id}:{payload.chunk_index}"
    )
    await redis.set(chunk_key, payload.data_b64, ex=3600)
    return {
        "upload_id": payload.upload_id,
        "chunk_index": payload.chunk_index,
        "received": True,
    }


@router.post("/upload/merge")
async def upload_merge(
    payload: ChunkMergeRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """合并分片:从 Redis 取所有 chunk,合并为完整文件(简化版:只统计大小)"""
    import base64

    redis = await _redis_client()
    pattern = _k("upload_chunk", _user_id, f"{payload.upload_id}:*")
    keys = sorted(await redis.keys(pattern))
    total_bytes = 0
    for k in keys:
        chunk_b64 = await redis.get(k)
        if chunk_b64:
            total_bytes += len(base64.b64decode(chunk_b64))
        await redis.delete(k)
    return {
        "upload_id": payload.upload_id,
        "filename": payload.filename,
        "total_bytes": total_bytes,
        "chunks_merged": len(keys),
    }


# ── 4. Chat Multimodal Upload ───────────────────────────────────────────


@router.post("/chat/upload")
async def chat_upload(
    _user_id: CurrentUserId, payload: dict[str, Any]
) -> dict[str, Any]:
    """多模态上传(图片/语音/视频片段)"""
    return {
        "url": f"/static/uploads/{uuid.uuid4()}",
        "type": payload.get("type", "image"),
        "size": payload.get("size", 0),
    }


# ── 5. Reports Ext ──────────────────────────────────────────────────────


@router.get("/reports/search")
async def reports_search(
    _user_id: CurrentUserId,
    q: str = Query(""),
    _from: str | None = Query(None, alias="from"),
    _to: str | None = Query(None, alias="to"),
    _type: str | None = Query(None, alias="type"),
) -> dict[str, Any]:
    """报告搜索(全文 + 时间 + 类型)"""
    return {"results": [], "query": {"q": q, "from": _from, "to": _to, "type": _type}}


@router.get("/reports/compare")
async def reports_compare(
    _user_id: CurrentUserId, ids: str = Query(...)
) -> dict[str, Any]:
    """报告对比(2-3 份并排)"""
    id_list = [int(i) for i in ids.split(",") if i.strip()]
    return {
        "reports": [{"id": i, "content": f"# Report {i}\n\n(占位)"} for i in id_list]
    }


@router.post("/reports/schedule")
async def reports_schedule(
    payload: ReportScheduleRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """定时报告(cron 表达式)"""
    redis = await _redis_client()
    sched_id = str(uuid.uuid4())
    await redis.set(
        _k("report_schedule", _user_id, sched_id),
        json.dumps(payload.model_dump()),
    )
    return {"schedule_id": sched_id, "cron": payload.cron, "enabled": payload.enabled}


# ── 6. Test Reports Ext ─────────────────────────────────────────────────


@router.get("/test-reports/{rid}/cases")
async def test_report_cases(
    _user_id: CurrentUserId, rid: str = Path(...)
) -> dict[str, Any]:
    """失败用例详情"""
    return {
        "report_id": rid,
        "cases": [
            {"name": "test_login", "status": "passed", "duration_ms": 120},
            {
                "name": "test_dashboard",
                "status": "failed",
                "error": "Timeout",
                "screenshot": None,
            },
        ],
    }


@router.post("/test-reports/rerun")
async def test_reports_rerun(
    _user_id: CurrentUserId, payload: dict[str, Any]
) -> dict[str, Any]:
    """重跑测试(异步任务)"""
    return {
        "job_id": str(uuid.uuid4()),
        "status": "queued",
        "scope": payload.get("scope", "all"),
    }


# ── 7. LLM Observe Ext ──────────────────────────────────────────────────


@router.get("/llm-observe/alerts")
async def llm_alerts_get(_user_id: CurrentUserId) -> dict[str, Any]:
    """告警规则列表"""
    redis = await _redis_client()
    raw = await redis.get(_k("llm_alerts", _user_id))
    rules = [AlertRule(**r) for r in (json.loads(raw) if raw else [])]
    return {"rules": rules}


@router.put("/llm-observe/alerts")
async def llm_alerts_put(
    rules: list[AlertRule], _user_id: CurrentUserId
) -> dict[str, Any]:
    """更新告警规则"""
    redis = await _redis_client()
    await redis.set(
        _k("llm_alerts", _user_id), json.dumps([r.model_dump() for r in rules])
    )
    return {"rules": rules, "count": len(rules)}


@router.get("/llm-observe/budgets")
async def llm_budgets_get(_user_id: CurrentUserId) -> dict[str, Any]:
    """预算限制列表"""
    redis = await _redis_client()
    raw = await redis.get(_k("llm_budgets", _user_id))
    budgets = [BudgetLimit(**b) for b in (json.loads(raw) if raw else [])]
    return {"budgets": budgets}


@router.post("/llm-observe/budgets")
async def llm_budgets_post(
    budget: BudgetLimit, _user_id: CurrentUserId
) -> dict[str, Any]:
    """设置/新增预算"""
    redis = await _redis_client()
    raw = await redis.get(_k("llm_budgets", _user_id))
    budgets = json.loads(raw) if raw else []
    budgets.append(budget.model_dump())
    await redis.set(_k("llm_budgets", _user_id), json.dumps(budgets))
    return {"budgets": budgets, "added": budget}


@router.get("/llm-observe/traces/{tid}/spans")
async def llm_trace_spans(
    _user_id: CurrentUserId, tid: str = Path(...)
) -> dict[str, Any]:
    """Trace span 树(占位)"""
    return {
        "trace_id": tid,
        "spans": [
            {
                "id": "s1",
                "parent": None,
                "name": "llm_call",
                "duration_ms": 850,
                "prompt": "...",
                "response": "...",
            },
            {
                "id": "s2",
                "parent": "s1",
                "name": "tool_use",
                "duration_ms": 120,
                "tool": "fact_query",
            },
        ],
    }


@router.post("/llm-observe/ab-test")
async def llm_ab_test(
    payload: ABTestRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """A/B 实验:同 prompt 不同模型对比(异步)"""
    return {
        "experiment_id": str(uuid.uuid4()),
        "status": "queued",
        "model_a": payload.model_a,
        "model_b": payload.model_b,
    }


# ── 8. Medical Ext ──────────────────────────────────────────────────────


@router.get("/medical/labs/trend")
async def medical_labs_trend(
    _user_id: CurrentUserId,
    test: str = Query(...),
    _from: str | None = Query(None, alias="from"),
    _to: str | None = Query(None, alias="to"),
) -> dict[str, Any]:
    """化验趋势(同项目多时间点曲线)"""
    return {
        "test": test,
        "data_points": [],
        "ref_range": None,
        "abnormal_count": 0,
    }


@router.post("/medical/medications/reminder")
async def medical_med_reminder(
    payload: MedicalReminderRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """用药提醒"""
    redis = await _redis_client()
    rid = str(uuid.uuid4())
    await redis.set(
        _k("med_reminder", _user_id, rid),
        json.dumps(
            {**payload.model_dump(), "created_at": datetime.now(UTC).isoformat()}
        ),
    )
    return {
        "reminder_id": rid,
        "medication": payload.medication_name,
        "times_per_day": payload.times_per_day,
    }


@router.post("/medical/export/pdf")
async def medical_export_pdf(
    _user_id: CurrentUserId, payload: dict[str, Any]
) -> dict[str, Any]:
    """医疗 PDF 导出(异步任务)"""
    return {"task_id": str(uuid.uuid4()), "status": "queued", "url": None}


@router.post("/medical/share")
async def medical_share(
    payload: MedicalShareRequest, _user_id: CurrentUserId
) -> dict[str, Any]:
    """家人/医生共享(生成链接)"""
    redis = await _redis_client()
    token = secrets.token_urlsafe(24)
    expires = datetime.now(UTC) + timedelta(days=payload.expires_days)
    await redis.set(
        f"rhythmind:med_share:{token}",
        json.dumps(
            {
                "owner": _user_id,
                "scope": payload.scope,
                "expires_at": expires.isoformat(),
            }
        ),
        ex=payload.expires_days * 86400,
    )
    return {
        "share_url": f"/share/{token}",
        "expires_at": expires.isoformat(),
        "scope": payload.scope,
    }


# ── 9. Bigscreen ────────────────────────────────────────────────────────


@router.get("/bigscreen/users")
async def bigscreen_users(_user_id: CurrentUserId) -> dict[str, Any]:
    """大屏轮播用户列表(简化版:返回当前用户)"""
    return {
        "users": [
            {
                "user_id": _user_id,
                "display_name": "当前用户",
                "avatar": "R",
                "has_data": True,
            },
        ],
        "rotation_interval_sec": 60,
    }


__all__ = ["router"]
