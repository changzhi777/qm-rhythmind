# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/health.py — 健康数据路由

Endpoints:
  POST /health/upload            — 上传健康数据（同步返回完整结果）
  POST /health/upload/stream     — 上传健康数据（SSE 流式进度推送）
  WS  /health/upload/stream/ws   — 上传健康数据（WebSocket 流式）
  POST /health/ingest            — 可穿戴设备 CSV 数据摄入
  POST /health/chat              — 文本对话（意图分类 → 路由工作流）
  GET  /health/memory            — 查看当前用户记忆摘要（调试用）
  GET  /health/pool/stats        — Agent 池诊断（调试用）
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import UTC
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sse_starlette.sse import EventSourceResponse

from rhythmind.api.deps import CurrentUserId, PoolDep, RouterDep
from rhythmind.api.rate_limit import (
    LIMIT_CHAT_PER_IP,
    LIMIT_CHAT_PER_USER,
    LIMIT_UPLOAD_PER_IP,
    LIMIT_UPLOAD_PER_USER,
    rate_limit_ip,
    rate_limit_user,
)
from rhythmind.api.schemas.health import (
    HealthChatRequest,
    HealthDataUploadRequest,
    WorkflowResultResponse,
)
from rhythmind.core.memory import MemoryManager
from rhythmind.orchestrator.workflows.swarm_data_coach import SwarmDataCoach

router = APIRouter(prefix="/health", tags=["health"])

# 限流依赖（每路由两层：per-user + per-IP）
_upload_limits = [
    Depends(rate_limit_user("upload", *LIMIT_UPLOAD_PER_USER)),
    Depends(rate_limit_ip("upload", *LIMIT_UPLOAD_PER_IP)),
]
_chat_limits = [
    Depends(rate_limit_user("chat", *LIMIT_CHAT_PER_USER)),
    Depends(rate_limit_ip("chat", *LIMIT_CHAT_PER_IP)),
]

_swarm = SwarmDataCoach()


# ── POST /health/upload ───────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=WorkflowResultResponse,
    summary="上传健康数据（同步，等待完整结果）",
    dependencies=_upload_limits,
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
    dependencies=_upload_limits,
    responses={
        200: {
            "description": "SSE 事件流",
            "content": {
                "text/event-stream": {
                    "example": (
                        "event: start\ndata: {\"session_id\": \"...\", \"message\": \"开始分析\"}\n\n"  # noqa: E501
                        "event: metrics_done\ndata: {\"load_level\": \"moderate\", ...}\n\n"  # noqa: E501
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
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ...',
            },
            body: JSON.stringify(payload),
        });
        const reader = res.body.getReader();
        // 解析 SSE 文本帧...
    """
    session_id = str(uuid.uuid4())
    raw_input = body.model_dump(exclude_none=True)

    async def event_generator() -> Any:
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


# ── WebSocket /health/upload/stream/ws ─────────────────────────────────────────

@router.websocket("/upload/stream/ws")
async def upload_health_data_stream_ws(websocket: WebSocket) -> None:
    """
    WebSocket 流式版本。协议：

    1. 客户端连接 ``ws://host/api/v1/health/upload/stream/ws?token=<jwt>``
    2. 服务端返回 ``{"type": "connected", "data": {"session_id": "..."}}``
    3. 客户端发送 JSON: ``{"input_data": {...}}``
    4. 服务端流式推送（与 SSE 相同的事件序列）::

         {"type": "start",         "data": {...}}
         {"type": "metrics_done",  "data": {...}}
         {"type": "data_done",     "data": {...}}
         {"type": "coach_done",    "data": {...}}
         {"type": "error",         "data": {"step": "...", "message": "..."}}
         {"type": "done",          "data": {...完整 SwarmResult.final_output>}}

    5. 服务端发送 ``{"type": "close"}`` 后关闭 WebSocket 连接

    前端 JS 示例::

        const ws = new WebSocket(
            'ws://localhost:8000/api/v1/health/upload/stream/ws?token=' + token
        );
        ws.onopen = () => ws.send(JSON.stringify({input_data: payload}));
        ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.type === 'done') { /* 完整结果在 msg.data */ }
        };
    """
    import json as _json

    # ── 1. JWT 鉴权（query param）───────────────────────────────────────
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        from jose import jwt as _jwt  # type: ignore[import-untyped]

        from rhythmind.config import settings
        payload = _jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub", "")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token: missing sub")
            return
    except Exception:
        await websocket.close(code=4001, reason="Token validation failed")
        return

    # ── 2. 接受连接 ─────────────────────────────────────────────────────
    await websocket.accept()

    # ── 3. 接收客户端消息（input_data）──────────────────────────────────
    try:
        client_msg = await websocket.receive_json()
    except Exception:
        await websocket.send_json({"type": "error", "data": {"message": "Invalid JSON"}})  # noqa: E501
        await websocket.close()
        return

    input_data = client_msg.get("input_data")
    if not input_data:
        await websocket.send_json(
            {"type": "error", "data": {"message": "Missing input_data"}}
        )
        await websocket.close()
        return

    # ── 4. 限流检查 ─────────────────────────────────────────────────────
    # 延迟导入：让测试能正确 monkeypatch（模块级导入在加载时被绑定）
    from rhythmind.api import rate_limit as rate_limit_mod
    limit_user_key = f"rl:user:upload:{user_id}"
    allowed, _, _ = await rate_limit_mod._check_and_incr(
        limit_user_key, *LIMIT_UPLOAD_PER_USER
    )
    if not allowed:
        await websocket.send_json({
            "type": "error",
            "data": {"message": "Rate limit exceeded. Please try again later."},
        })
        await websocket.close()
        return

    # ── 5. 执行 Swarm 流式工作流 ─────────────────────────────────────────
    from rhythmind.api.deps import get_pool
    pool = get_pool()
    session_id = str(uuid.uuid4())

    await websocket.send_json({
        "type": "connected",
        "data": {"session_id": session_id, "user_id": user_id},
    })

    try:
        async with pool.acquire(user_id) as agents:
            async for event in _swarm.run_stream(
                user_id=user_id,
                session_id=session_id,
                input_data=input_data,
                metrics_agent=agents.metrics,
                data_agent=agents.data,
                coach_agent=agents.coach,
            ):
                # 将 SSE 格式 {"event": "xxx", "data": {...}}
                # 转换为 WebSocket JSON 帧 {"type": "xxx", "data": {...}}
                await websocket.send_json({
                    "type": event.get("event", "unknown"),
                    "data": _json.loads(event.get("data", "{}")),
                })
    except WebSocketDisconnect:
        pass  # 客户端主动关闭
    except Exception as exc:
        with contextlib.suppress(Exception):
            await websocket.send_json({
                "type": "error",
                "data": {"step": "stream", "message": str(exc)},
            })
    finally:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "close"})
        await websocket.close()


# ── POST /health/chat ─────────────────────────────────────────────────────────

@router.post(
    "/chat",
    response_model=WorkflowResultResponse,
    summary="文本对话（意图分类 → 路由）",
    dependencies=_chat_limits,
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    """返回 AgentPool 当前状态，含池大小和各用户闲置时间。仅 debug 模式。"""
    from rhythmind.config import settings
    if not settings.debug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return pool.stats()


# ── POST /health/ingest ───────────────────────────────────────────────────────

@router.post(
    "/ingest",
    summary="接收可穿戴设备导出数据（CSV）",
    responses={
        200: {"description": "数据摄入成功"},
        400: {"description": "CSV 格式错误"},
        401: {"description": "未授权"},
        422: {"description": "数据校验失败"},
    },
)
async def ingest_wearable_data(
    file: UploadFile,
    user_id: CurrentUserId,
    source: str = Query(
        default="manual",
        description="数据来源：apple_health / google_health / fitbit / manual",
    ),
) -> dict[str, Any]:
    """
    接收可穿戴设备（Apple Health / Google Health / Fitbit）导出的 CSV，
    解析后写入 InfluxDB，作为 MetricsAgent 的数据源之一。

    CSV 格式（必需列：timestamp）：
      timestamp,heart_rate,steps,sleep_minutes,spo2,blood_pressure_systolic,blood_pressure_diastolic
      2026-05-12T08:00:00Z,65,1200,0,98,
      2026-05-12T09:00:00Z,72,300,480,97,120,80

    关联 PR：WEARABLE_DEVICE_RESEARCH.md §P0
    """
    import csv
    import io
    from datetime import datetime

    # ── 1. 读取并解析 CSV ────────────────────────────────────────────
    if not (file.filename or "").endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are supported",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8-sig")  # 尝试带 BOM 的 UTF-8

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty or invalid CSV",
        )

    # ── 2. 解析行 → InfluxDB 数据点 ─────────────────────────────────
    from rhythmind.adapters.influx_client import InfluxClient, MetricPoint

    influx = InfluxClient()
    points: list[MetricPoint] = []
    errors: list[str] = []

    for row_num, row in enumerate(reader, start=2):
        try:
            ts_str = row.get("timestamp", "").strip()
            if not ts_str:
                errors.append(f"Row {row_num}: missing timestamp")
                continue

            # 解析时间（支持 ISO 8601 和常见格式）
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                ts = ts.replace(tzinfo=UTC)

            hr_str = row.get("heart_rate", "").strip()
            steps_str = row.get("steps", "").strip()
            sleep_str = row.get("sleep_minutes", "").strip()
            spo2_str = row.get("spo2", "").strip()
            bp_sys_str = row.get("blood_pressure_systolic", "").strip()
            bp_dia_str = row.get("blood_pressure_diastolic", "").strip()

            # 跳过全空行
            if not any([hr_str, steps_str, sleep_str, spo2_str, bp_sys_str]):
                continue

            point = MetricPoint(
                user_id=user_id,
                source=source,
                sport_type="general",
                fields={
                    k: v
                    for k, v in {
                        "heart_rate": int(hr_str) if hr_str else None,
                        "steps": int(steps_str) if steps_str else None,
                        "sleep_minutes": int(sleep_str) if sleep_str else None,
                        "spo2": float(spo2_str) if spo2_str else None,
                        "blood_pressure_systolic":
                            int(bp_sys_str) if bp_sys_str else None,
                        "blood_pressure_diastolic":
                            int(bp_dia_str) if bp_dia_str else None,
                    }.items()
                    if v is not None
                },
                ts=ts,
            )
            points.append(point)
        except Exception as exc:
            errors.append(f"Row {row_num}: {exc}")

    if not points:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No valid data points. Errors: {errors[:5]}",
        )

    # ── 3. 批量写入 InfluxDB ─────────────────────────────────────────
    write_ok = await influx.write_metrics(points)

    return {
        "status": "success" if write_ok else "partial",
        "user_id": user_id,
        "source": source,
        "rows_parsed": len(points),
        "errors": errors[:10],  # 最多返回 10 条
        "write_ok": write_ok,
    }
