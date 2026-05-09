# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/health.py — 健康数据路由

Endpoints:
  POST /health/upload         — 上传健康数据（同步返回完整结果）
  POST /health/upload/stream  — 上传健康数据（SSE 流式进度推送）
  POST /health/chat           — 文本对话（意图分类 → 路由工作流）
  GET  /health/memory         — 查看当前用户记忆摘要（调试用）
  GET  /health/pool/stats     — Agent 池诊断（调试用）
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from rhythmind.api.deps import CurrentUserId, PoolDep, RouterDep
from rhythmind.api.schemas.health import (
    HealthChatRequest,
    HealthDataUploadRequest,
    WorkflowResultResponse,
)
from rhythmind.core.memory import MemoryManager
from rhythmind.orchestrator.workflows.swarm_data_coach import SwarmDataCoach

router = APIRouter(prefix="/health", tags=["health"])

_swarm = SwarmDataCoach()


# ── POST /health/upload ───────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=WorkflowResultResponse,
    summary="上传健康数据（同步，等待完整结果）",
)
async def upload_health_data(
    body: HealthDataUploadRequest,
    user_id: CurrentUserId,
    health_router: RouterDep,
    pool: PoolDep,
) -> WorkflowResultResponse:
    """
    接收结构化健康指标，触发 MetricsAgent → DataAgent → CoachAgent Swarm。

    使用 Agent Pool 复用 Agent 实例，避免重复初始化开销。
    返回：数据解读报告 + 训练计划（等待全部完成后一次返回）。
    """
    session_id = str(uuid.uuid4())
    raw_input = body.model_dump(exclude_none=True)

    async with pool.acquire(user_id) as agents:
        swarm_result = await _swarm.run(
            user_id=user_id,
            session_id=session_id,
            input_data=raw_input,
            metrics_agent=agents.metrics,
            data_agent=agents.data,
            coach_agent=agents.coach,
        )

    if not swarm_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="数据分析合规检查未通过",
        )

    return WorkflowResultResponse(
        status="success",
        session_id=session_id,
        data=swarm_result.final_output,
    )


# ── POST /health/upload/stream ────────────────────────────────────────────────

@router.post(
    "/upload/stream",
    summary="上传健康数据（SSE 流式进度推送）",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "SSE 事件流",
            "content": {
                "text/event-stream": {
                    "example": (
                        "event: start\ndata: {\"session_id\": \"...\", \"message\": \"开始分析\"}\n\n"
                        "event: metrics_done\ndata: {\"load_level\": \"moderate\", ...}\n\n"
                        "event: data_done\ndata: {\"summary\": \"...\", ...}\n\n"
                        "event: coach_done\ndata: {\"plan_name\": \"...\", ...}\n\n"
                        "event: done\ndata: {完整 SwarmResult.final_output}\n\n"
                    )
                }
            },
        }
    },
)
async def upload_health_data_stream(
    body: HealthDataUploadRequest,
    user_id: CurrentUserId,
    pool: PoolDep,
) -> EventSourceResponse:
    """
    SSE 流式版本。客户端连接后立即收到每个 Agent 的进度事件：

    - ``start``        — 工作流启动
    - ``metrics_done`` — 指标分析完成（含异常数、负荷级别）
    - ``data_done``    — 数据解读完成（含摘要）
    - ``coach_done``   — 训练计划完成（含计划名、激励语）
    - ``done``         — 完整 JSON 结果
    - ``error``        — 任意步骤失败

    前端 JS 示例（fetch + ReadableStream）::

        const res = await fetch('/api/v1/health/upload/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ...'},
            body: JSON.stringify(payload),
        });
        const reader = res.body.getReader();
        // 解析 SSE 文本帧...
    """
    session_id = str(uuid.uuid4())
    raw_input = body.model_dump(exclude_none=True)

    async def event_generator():
        async with pool.acquire(user_id) as agents:
            async for event in _swarm.run_stream(
                user_id=user_id,
                session_id=session_id,
                input_data=raw_input,
                metrics_agent=agents.metrics,
                data_agent=agents.data,
                coach_agent=agents.coach,
            ):
                yield event

    return EventSourceResponse(event_generator())


# ── POST /health/chat ─────────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=WorkflowResultResponse,
    summary="文本对话（意图分类 → 路由）",
)
async def health_chat(
    body: HealthChatRequest,
    user_id: CurrentUserId,
    health_router: RouterDep,
) -> WorkflowResultResponse:
    """
    自然语言对话入口。

    意图自动分类后路由到对应工作流：
      - 上传/同步 → MetricsAgent + DataAgent + CoachAgent
      - 饮食问题 → DietAgent（Phase 2）
      - 疼痛/损伤 → RehabAgent（Phase 2）
    """
    session_id = str(uuid.uuid4())
    raw_input = {"text": body.text, **body.context}

    result = await health_router.route(
        user_id=user_id,
        raw_input=raw_input,
        session_id=session_id,
    )

    return WorkflowResultResponse(
        status=result.status.value,
        session_id=session_id,
        data=result.data,
        message=result.message,
    )


# ── GET /health/memory ────────────────────────────────────────────────────────

@router.get(
    "/memory",
    summary="查看用户记忆摘要（调试）",
)
async def get_memory_summary(
    user_id: CurrentUserId,
) -> dict:
    """返回当前用户所有 Agent 的最近记忆条目（仅 debug 模式）。"""
    from rhythmind.config import settings
    if not settings.debug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    results = {}
    for agent in ("metrics_agent", "data_agent", "coach_agent"):
        mgr = MemoryManager(user_id=user_id, agent=agent)
        recall = await mgr.recall(task_type="", limit=10)
        results[agent] = recall.to_dict()

    return {"user_id": user_id, "memory": results}


# ── GET /health/pool/stats ────────────────────────────────────────────────────

@router.get(
    "/pool/stats",
    summary="Agent 池状态诊断（调试）",
)
async def pool_stats(
    user_id: CurrentUserId,
    pool: PoolDep,
) -> dict:
    """返回 AgentPool 当前状态，含池大小和各用户闲置时间。仅 debug 模式。"""
    from rhythmind.config import settings
    if not settings.debug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return pool.stats()
