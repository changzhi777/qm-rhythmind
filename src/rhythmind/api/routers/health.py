# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/health.py — 健康数据路由

Endpoints:
  POST /health/upload  — 上传结构化健康数据（触发 DataAgent → CoachAgent Swarm）
  POST /health/chat    — 文本对话（意图分类 → 路由工作流）
  GET  /health/memory  — 查看当前用户记忆摘要（调试用，生产可关闭）
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from rhythmind.api.deps import CurrentUserId, RouterDep
from rhythmind.api.schemas.health import (
    HealthChatRequest,
    HealthDataUploadRequest,
    WorkflowResultResponse,
)
from rhythmind.core.memory import MemoryManager
from rhythmind.orchestrator.router import WorkflowStatus

router = APIRouter(prefix="/health", tags=["health"])


@router.post(
    "/upload",
    response_model=WorkflowResultResponse,
    summary="上传健康数据（触发 DataAgent + CoachAgent）",
)
async def upload_health_data(
    body: HealthDataUploadRequest,
    user_id: CurrentUserId,
    health_router: RouterDep,
) -> WorkflowResultResponse:
    """
    接收结构化健康指标，触发 DataAgent → CoachAgent Swarm。

    - 支持多来源：garmin / apple / huawei / xiaomi / manual
    - 返回：数据解读报告 + 训练计划
    """
    session_id = str(uuid.uuid4())
    raw_input = body.model_dump(exclude_none=True)

    result = await health_router.route(
        user_id=user_id,
        raw_input=raw_input,
        session_id=session_id,
    )

    if result.status == WorkflowStatus.BLOCKED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.message,
        )
    if result.status == WorkflowStatus.THROTTLED:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=result.message,
        )
    if result.status == WorkflowStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.message,
        )

    return WorkflowResultResponse(
        status=result.status.value,
        session_id=result.session_id,
        data=result.data,
    )


@router.post(
    "/chat",
    response_model=WorkflowResultResponse,
    summary="文本对话（意图分类→路由）",
)
async def health_chat(
    body: HealthChatRequest,
    user_id: CurrentUserId,
    health_router: RouterDep,
) -> WorkflowResultResponse:
    """
    自然语言对话入口。

    意图自动分类后路由到对应工作流：
      - 上传/同步 → DataAgent + CoachAgent
      - 饮食问题 → DietAgent
      - 疼痛/损伤 → RehabAgent（多 Agent Graph）
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


@router.get(
    "/memory",
    summary="查看用户记忆摘要（调试）",
)
async def get_memory_summary(
    user_id: CurrentUserId,
) -> dict:
    """
    返回当前用户所有 Agent 的最近记忆条目（调试端点）。
    生产环境可通过 settings.debug=False 关闭。
    """
    from rhythmind.config import settings
    if not settings.debug:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    # 拉取 data_agent 和 coach_agent 的记忆
    results = {}
    for agent in ("data_agent", "coach_agent", "diet_agent", "rehab_agent"):
        mgr = MemoryManager(user_id=user_id, agent=agent)
        recall = await mgr.recall(task_type="", limit=10)
        results[agent] = recall.to_dict()

    return {"user_id": user_id, "memory": results}
