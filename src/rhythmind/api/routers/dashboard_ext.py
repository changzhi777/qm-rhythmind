"""
api/routers/dashboard_ext.py — Dashboard 扩展端点(2026-06-24 frontend-polish Stage 5)

新增端点:
  GET  /api/v1/goals                 — 获取用户个人目标
  PUT  /api/v1/goals                 — 更新用户个人目标
  GET  /api/v1/dashboard/comparison  — 同比/环比对比数据
  GET  /api/v1/thresholds            — 获取 KPI 阈值配置
  PUT  /api/v1/thresholds            — 更新 KPI 阈值配置
  POST /api/v1/users/switch/{id}     — 切换用户(开发模式)

Why:
  前端 /dashboard 接入个人目标 + 同比对比 + 5 状态阈值动态化需要后端配合。
  这些端点暂以 Redis 持久化(用户级 namespace),后续可迁 PG。
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from rhythmind.api.deps import CurrentUserId
from rhythmind.api.routers._common import _fm
from rhythmind.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["dashboard-ext"])

# ── Redis 客户端(惰性初始化) ─────────────────────────────────────────────
_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """惰性获取 Redis 客户端(从 settings.redis_url 读取)"""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _redis_client


def _kpi_goals_key(user_id: str) -> str:
    return f"rhythmind:goals:{user_id}"


def _kpi_thresholds_key(user_id: str) -> str:
    return f"rhythmind:thresholds:{user_id}"


# ── Schemas ─────────────────────────────────────────────────────────────


class Goal(BaseModel):
    metric: str
    target: float
    deadline: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class GoalUpdate(BaseModel):
    metric: str
    target: float
    deadline: str | None = None


class GoalsResponse(BaseModel):
    user_id: str
    goals: list[Goal]


class ThresholdRange(BaseModel):
    excellent: tuple[float, float] | None = None
    good: tuple[float, float]
    average: tuple[float, float] | None = None
    concerned: tuple[float, float] | None = None
    danger: tuple[float, float] | None = None


class ThresholdOverride(BaseModel):
    metric: str
    ranges: ThresholdRange


class ThresholdsResponse(BaseModel):
    user_id: str
    overrides: dict[str, ThresholdRange] = Field(default_factory=dict)


class ComparisonDataPoint(BaseModel):
    date: str
    value: float | None


class ComparisonResponse(BaseModel):
    metric: str
    current: list[ComparisonDataPoint]
    previous: list[ComparisonDataPoint]
    diff: float
    diff_pct: float
    range: str


class SwitchResponse(BaseModel):
    user_id: str
    success: bool
    message: str


# ── Goals 端点 ──────────────────────────────────────────────────────────


@router.get("/goals", response_model=GoalsResponse)
async def get_goals(user_id: CurrentUserId) -> GoalsResponse:
    """获取用户个人目标列表"""
    redis = await _get_redis()
    raw = await redis.get(_kpi_goals_key(user_id))
    goals: list[dict[str, Any]] = json.loads(raw) if raw else []
    return GoalsResponse(user_id=user_id, goals=[Goal(**g) for g in goals])


@router.put("/goals", response_model=GoalsResponse)
async def put_goals(payload: list[GoalUpdate], user_id: CurrentUserId) -> GoalsResponse:
    """批量更新用户个人目标(覆盖整个列表)"""
    redis = await _get_redis()
    now = datetime.now(UTC).isoformat()
    goals = [
        Goal(
            metric=g.metric,
            target=g.target,
            deadline=g.deadline,
            created_at=now,
        ).model_dump()
        for g in payload
    ]
    await redis.set(_kpi_goals_key(user_id), json.dumps(goals))
    return GoalsResponse(user_id=user_id, goals=[Goal(**g) for g in goals])


# ── Comparison 端点 ─────────────────────────────────────────────────────


@router.get("/dashboard/comparison", response_model=ComparisonResponse)
async def dashboard_comparison(
    user_id: CurrentUserId,
    metric: str,
    range: str = "-7d",
) -> ComparisonResponse:
    """同比/环比对比:从 FactManager 取当前周期 + 上一周期"""
    fm = _fm(user_id)
    days = _parse_range_days(range)
    if days <= 0:
        raise HTTPException(status_code=400, detail=f"Invalid range: {range}")

    current_data = await _fetch_metric_series(
        fm, user_id, metric, days, offset_days=0,
    )
    previous_data = await _fetch_metric_series(
        fm, user_id, metric, days, offset_days=days,
    )

    curr_avg = _avg(current_data)
    prev_avg = _avg(previous_data)
    diff = curr_avg - prev_avg
    diff_pct = (diff / prev_avg * 100) if prev_avg != 0 else 0.0

    return ComparisonResponse(
        metric=metric,
        current=[
            ComparisonDataPoint(date=d["date"], value=d["value"])
            for d in current_data
        ],
        previous=[
            ComparisonDataPoint(date=d["date"], value=d["value"])
            for d in previous_data
        ],
        diff=round(diff, 2),
        diff_pct=round(diff_pct, 2),
        range=range,
    )


def _parse_range_days(range_str: str) -> int:
    """解析 -7d / -30d / -90d 格式"""
    s = range_str.strip().lower().lstrip("-")
    if s.endswith("d"):
        try:
            return int(s[:-1])
        except ValueError:
            return 0
    return 0


async def _fetch_metric_series(
    fm: Any, user_id: str, metric: str, days: int, offset_days: int
) -> list[dict[str, Any]]:
    """从 FactManager 拉取指定时间窗口的指标序列。
    简化实现:返回固定占位序列,生产应接 InfluxDB 或时序表。"""
    # 占位:返回空序列,由前端用 chartjs 平滑曲线兜底
    # 真实场景需扩展 fm 接口
    return []


def _avg(data: list[dict[str, Any]]) -> float:
    vals = [d["value"] for d in data if d.get("value") is not None]
    return sum(vals) / len(vals) if vals else 0.0


# ── Thresholds 端点 ─────────────────────────────────────────────────────


@router.get("/thresholds", response_model=ThresholdsResponse)
async def get_thresholds(user_id: CurrentUserId) -> ThresholdsResponse:
    """获取用户 KPI 阈值覆写"""
    redis = await _get_redis()
    raw = await redis.get(_kpi_thresholds_key(user_id))
    overrides: dict[str, Any] = json.loads(raw) if raw else {}
    return ThresholdsResponse(
        user_id=user_id,
        overrides={k: ThresholdRange(**v) for k, v in overrides.items()},
    )


@router.put("/thresholds", response_model=ThresholdsResponse)
async def put_thresholds(
    payload: list[ThresholdOverride], user_id: CurrentUserId
) -> ThresholdsResponse:
    """批量更新用户 KPI 阈值覆写"""
    redis = await _get_redis()
    overrides = {o.metric: o.ranges.model_dump(mode="json") for o in payload}
    await redis.set(_kpi_thresholds_key(user_id), json.dumps(overrides))
    return ThresholdsResponse(
        user_id=user_id,
        overrides={k: ThresholdRange(**v) for k, v in overrides.items()},
    )


# ── User Switch 端点 ───────────────────────────────────────────────────


@router.post("/users/switch/{user_id}", response_model=SwitchResponse)
async def switch_user(
    user_id: str = Path(..., description="目标用户 ID"),
    current_user: CurrentUserId = "",  # noqa: ARG001 — 仅用于触发鉴权依赖
) -> SwitchResponse:
    """切换当前会话用户(开发模式):返回目标 user_id,前端写入 localStorage"""
    # 生产环境应禁用,此处仅返回 user_id 让前端 setAuthToken
    return SwitchResponse(
        user_id=user_id, success=True, message="切换成功,请前端更新 token",
    )


__all__ = ["router"]