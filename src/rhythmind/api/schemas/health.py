# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/schemas/health.py — 健康数据 API 请求/响应模型
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class HRZones(BaseModel):
    z1: float | None = None
    z2: float | None = None
    z3: float | None = None
    z4: float | None = None
    z5: float | None = None


class HealthDataUploadRequest(BaseModel):
    """
    /health/upload 请求体。

    支持 Garmin / Apple / Huawei / Xiaomi / 手动输入。
    """
    source: str = Field(
        ..., pattern="^(garmin|apple|huawei|xiaomi|manual)$",
        description="数据来源"
    )
    sport_type: str = Field(default="general", description="运动类型")
    user_goal: str = Field(default="健康维护", description="用户目标")

    # 心率
    heart_rate_avg: float | None = Field(None, ge=20, le=250)
    heart_rate_max: float | None = Field(None, ge=20, le=250)
    heart_rate_zones: HRZones | None = None

    # 运动
    steps: int | None = Field(None, ge=0)
    distance_km: float | None = Field(None, ge=0)
    calories: int | None = Field(None, ge=0)

    # 睡眠
    sleep_hours: float | None = Field(None, ge=0, le=24)

    # 心率变异性
    hrv: float | None = Field(None, ge=0)

    # 体成分（来自体脂秤 OCR）
    body_fat_pct: float | None = Field(None, ge=0, le=100)
    muscle_mass_kg: float | None = Field(None, ge=0)
    water_pct: float | None = Field(None, ge=0, le=100)
    visceral_fat: int | None = Field(None, ge=0)

    # 原始数据透传（存档用）
    source_raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("heart_rate_max")
    @classmethod
    def max_gte_avg(cls, v: float | None, info: Any) -> float | None:
        avg = info.data.get("heart_rate_avg")
        if v is not None and avg is not None and v < avg:
            raise ValueError("heart_rate_max 不能小于 heart_rate_avg")
        return v


class WorkflowResultResponse(BaseModel):
    """统一 API 响应格式。"""
    status: str
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class HealthChatRequest(BaseModel):
    """
    /health/chat 对话请求体（文本驱动，意图分类后路由）。
    """
    text: str = Field(..., min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
