# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
api/routers/medical.py — 医疗数据 API 路由

Endpoints:
  POST /medical/analyze      — 综合健康分析
  GET  /medical/timeline     — 临床事件时间线
  GET  /medical/medications  — 用药列表 + 审查
  GET  /medical/labs/{test}  — 化验结果趋势

数据来源：med_* 表（通过 SQLAlchemy 异步查询）
AI 解读：MedicalAdvisor（继承精简后的 HermesBase）
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from rhythmind.agents.medical_advisor import MedicalAdvisor
from rhythmind.api.deps import CurrentUserId
from rhythmind.api.rate_limit import rate_limit_ip, rate_limit_user
from rhythmind.core.hermes_base import AgentContext

router = APIRouter(prefix="/medical", tags=["medical"])

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# 医疗端点限流（较健康上传宽松）
_med_limits = [
    Depends(rate_limit_user("medical", 20, 300)),
    Depends(rate_limit_ip("medical", 30, 300)),
]


# ── 响应模型 ────────────────────────────────────────────────────────────────

class MedicalAnalysisResponse(BaseModel):
    status: str
    session_id: str
    summary: str
    insights: list[str]
    concerns: list[str]
    recommendations: list[str]
    risk_flags: list[str]
    confidence: float


class TimelineResponse(BaseModel):
    status: str
    session_id: str
    events: list[dict[str, Any]]
    summary: str
    insights: list[str]
    recommendations: list[str]


class MedicationsResponse(BaseModel):
    status: str
    session_id: str
    medications: list[dict[str, Any]]
    summary: str
    insights: list[str]
    concerns: list[str]
    recommendations: list[str]


class LabsResponse(BaseModel):
    status: str
    session_id: str
    test_name: str
    results: list[dict[str, Any]]
    summary: str
    insights: list[str]
    concerns: list[str]
    recommendations: list[str]


# ── DB 查询辅助（共享 session） ────────────────────────────────────────────

@asynccontextmanager
async def _db_session() -> AsyncGenerator[Any, None]:
    from rhythmind.core.memory.manager import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


async def _query_patient(user_id: str, session: AsyncSession) -> dict[str, Any]:
    from sqlalchemy import select

    from rhythmind.db.medical_models import MedPatientProfile

    result = await session.execute(
        select(MedPatientProfile).where(
            MedPatientProfile.user_id == user_id
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {}
    return {
        "gender": profile.gender,
        "birth_year": profile.birth_year,
        "blood_type": profile.blood_type,
    }


async def _query_diagnoses(
    user_id: str, session: AsyncSession, active_only: bool = True,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from rhythmind.db.medical_models import MedDiagnosis

    stmt = select(MedDiagnosis).where(MedDiagnosis.user_id == user_id)
    if active_only:
        stmt = stmt.where(MedDiagnosis.is_active.is_(True))
    stmt = stmt.order_by(MedDiagnosis.diagnosis_date.desc())
    result = await session.execute(stmt)
    return [
        {
            "diagnosis_name": r.diagnosis_name,
            "diagnosis_date": str(r.diagnosis_date),
            "diagnosis_type": r.diagnosis_type,
            "icd_code": r.icd_code,
            "hospital": r.hospital,
            "is_active": r.is_active,
        }
        for r in result.scalars().all()
    ]


async def _query_events(
    user_id: str,
    session: AsyncSession,
    event_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from rhythmind.db.medical_models import MedClinicalEvent

    stmt = select(MedClinicalEvent).where(
        MedClinicalEvent.user_id == user_id,
    )
    if event_type:
        stmt = stmt.where(MedClinicalEvent.event_type == event_type)
    stmt = stmt.order_by(MedClinicalEvent.event_date.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        {
            "event_date": str(r.event_date),
            "event_type": r.event_type,
            "hospital": r.hospital,
            "department": r.department,
            "duration_days": r.duration_days,
            "cost": r.cost,
            "details": r.details,
        }
        for r in result.scalars().all()
    ]


async def _query_medications(
    user_id: str,
    session: AsyncSession,
    status_filter: str | None = "active",
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from rhythmind.db.medical_models import MedMedication

    stmt = select(MedMedication).where(MedMedication.user_id == user_id)
    if status_filter:
        stmt = stmt.where(MedMedication.status == status_filter)
    stmt = stmt.order_by(MedMedication.start_date.desc())
    result = await session.execute(stmt)
    return [
        {
            "medication_name": r.medication_name,
            "dose": r.dose,
            "route": r.route,
            "frequency": r.frequency,
            "purpose": r.purpose,
            "start_date": str(r.start_date),
            "end_date": str(r.end_date) if r.end_date else None,
            "status": r.status,
            "prescriber": r.prescriber,
        }
        for r in result.scalars().all()
    ]


async def _query_lab_results(
    user_id: str,
    session: AsyncSession,
    test_name: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from rhythmind.db.medical_models import MedLabResult

    stmt = select(MedLabResult).where(MedLabResult.user_id == user_id)
    if test_name:
        stmt = stmt.where(MedLabResult.test_name == test_name)
    stmt = stmt.order_by(MedLabResult.test_date.desc()).limit(limit)
    result = await session.execute(stmt)
    return [
        {
            "test_name": r.test_name,
            "test_date": str(r.test_date),
            "value": r.value,
            "value_str": r.value_str,
            "unit": r.unit,
            "ref_range": r.ref_range,
            "flag": r.flag,
            "specimen": r.specimen,
        }
        for r in result.scalars().all()
    ]


# ── POST /medical/analyze ──────────────────────────────────────────────────

@router.post(
    "/analyze",
    response_model=MedicalAnalysisResponse,
    summary="综合健康分析（AI 解读）",
    dependencies=_med_limits,
)
async def analyze_health(
    user_id: CurrentUserId,
) -> MedicalAnalysisResponse:
    """
    基于患者所有医疗数据（诊断+用药+化验+事件），
    通过 MedicalAdvisor LLM 生成综合健康分析。

    包含：健康洞察、风险提示、复诊建议。
    """
    session_id = str(uuid.uuid4())

    async with _db_session() as db:
        patient = await _query_patient(user_id, db)
        diagnoses = await _query_diagnoses(user_id, db)
        medications = await _query_medications(user_id, db)
        lab_results = await _query_lab_results(user_id, db, limit=30)
        events = await _query_events(user_id, db, limit=20)

    if not patient and not diagnoses and not medications and not lab_results:
        # 2026-06-25: 无数据返回 200 + 占位响应,避免前端 404 误判为错误
        return MedicalAnalysisResponse(
            status="no_data",
            session_id=session_id,
            summary="该用户暂无医疗数据,无法生成综合分析。",
            insights=[],
            concerns=[],
            recommendations=[],
            risk_flags=[],
            confidence=0.0,
        )

    advisor = MedicalAdvisor(user_id=user_id)
    ctx = AgentContext(
        user_id=user_id,
        session_id=session_id,
        task_type="medical_analyze",
        input_data={
            "task_type": "analyze",
            "patient": patient,
            "diagnoses": diagnoses,
            "events": events,
            "lab_results": lab_results,
            "medications": medications,
        },
    )
    run_result = await advisor.run(ctx)

    if not run_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="医疗分析合规检查未通过",
        )

    output = run_result.output or {}
    return MedicalAnalysisResponse(
        status="success",
        session_id=session_id,
        summary=output.get("summary", ""),
        insights=output.get("insights", []),
        concerns=output.get("concerns", []),
        recommendations=output.get("recommendations", []),
        risk_flags=output.get("risk_flags", []),
        confidence=run_result.compliance.confidence,
    )


# ── GET /medical/timeline ──────────────────────────────────────────────────

@router.get(
    "/timeline",
    response_model=TimelineResponse,
    summary="临床事件时间线",
    dependencies=_med_limits,
)
async def get_timeline(
    user_id: CurrentUserId,
    event_type: str | None = Query(None, description="筛选事件类型"),
    limit: int = Query(50, ge=1, le=200),
) -> TimelineResponse:
    """返回用户临床事件时间线，可选 AI 梳理。"""
    session_id = str(uuid.uuid4())

    async with _db_session() as db:
        events = await _query_events(
            user_id, db, event_type=event_type, limit=limit,
        )

    if not events:
        # 2026-06-25: 无数据返回 200 + 空 events,避免前端 404 误判为错误
        return TimelineResponse(
            status="success",
            session_id=session_id,
            events=[],
            summary="",
            insights=[],
            recommendations=[],
        )

    async with _db_session() as db:
        patient = await _query_patient(user_id, db)

    advisor = MedicalAdvisor(user_id=user_id)
    ctx = AgentContext(
        user_id=user_id,
        session_id=session_id,
        task_type="medical_timeline",
        input_data={
            "task_type": "timeline",
            "patient": patient,
            "events": events,
        },
    )
    run_result = await advisor.run(ctx)

    output = run_result.output or {}
    return TimelineResponse(
        status="success",
        session_id=session_id,
        events=events,
        summary=output.get("summary", ""),
        insights=output.get("insights", []),
        recommendations=output.get("recommendations", []),
    )


# ── GET /medical/medications ───────────────────────────────────────────────

@router.get(
    "/medications",
    response_model=MedicationsResponse,
    summary="用药列表 + AI 审查",
    dependencies=_med_limits,
)
async def get_medications(
    user_id: CurrentUserId,
    status_filter: str | None = Query(
        "active", description="active | all | discontinued",
    ),
) -> MedicationsResponse:
    """返回用户用药记录，通过 AI 审查潜在交互。"""
    session_id = str(uuid.uuid4())

    async with _db_session() as db:
        medications = await _query_medications(
            user_id, db,
            status_filter=None if status_filter == "all" else status_filter,
        )
        diagnoses = await _query_diagnoses(user_id, db)

    if not medications:
        # 2026-06-25: 无数据返回 200 + 空 medications
        return MedicationsResponse(
            status="success",
            session_id=session_id,
            medications=[],
            summary="",
            insights=[],
            concerns=[],
            recommendations=[],
        )

    advisor = MedicalAdvisor(user_id=user_id)
    ctx = AgentContext(
        user_id=user_id,
        session_id=session_id,
        task_type="medical_medications",
        input_data={
            "task_type": "medications",
            "diagnoses": diagnoses,
            "medications": medications,
        },
    )
    run_result = await advisor.run(ctx)

    output = run_result.output or {}
    return MedicationsResponse(
        status="success",
        session_id=session_id,
        medications=medications,
        summary=output.get("summary", ""),
        insights=output.get("insights", []),
        concerns=output.get("concerns", []),
        recommendations=output.get("recommendations", []),
    )


# ── GET /medical/labs (all results, no LLM) ───────────────────────────────

class AllLabsResponse(BaseModel):
    status: str
    results: list[dict[str, Any]]


@router.get(
    "/labs",
    response_model=AllLabsResponse,
    summary="所有化验结果（纯数据，无 AI 解读）",
    dependencies=_med_limits,
)
async def get_all_lab_results(
    user_id: CurrentUserId,
    limit: int = Query(100, ge=1, le=500),
) -> AllLabsResponse:
    """返回用户所有化验结果（不调用 LLM，纯数据库查询）。"""
    async with _db_session() as db:
        results = await _query_lab_results(user_id, db, test_name=None, limit=limit)

    return AllLabsResponse(status="success", results=results)


# ── GET /medical/labs/{test} ───────────────────────────────────────────────

@router.get(
    "/labs/{test}",
    response_model=LabsResponse,
    summary="化验结果趋势",
    dependencies=_med_limits,
)
async def get_lab_results(
    test: str,
    user_id: CurrentUserId,
    limit: int = Query(20, ge=1, le=100),
) -> LabsResponse:
    """返回特定化验项目的历次结果，含 AI 趋势解读。"""
    session_id = str(uuid.uuid4())

    async with _db_session() as db:
        results = await _query_lab_results(
            user_id, db, test_name=test, limit=limit,
        )
        diagnoses = await _query_diagnoses(user_id, db)

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到 {test} 的化验结果",
        )

    advisor = MedicalAdvisor(user_id=user_id)
    ctx = AgentContext(
        user_id=user_id,
        session_id=session_id,
        task_type="medical_labs",
        input_data={
            "task_type": "labs",
            "diagnoses": diagnoses,
            "lab_results": results,
        },
    )
    run_result = await advisor.run(ctx)

    output = run_result.output or {}
    return LabsResponse(
        status="success",
        session_id=session_id,
        test_name=test,
        results=results,
        summary=output.get("summary", ""),
        insights=output.get("insights", []),
        concerns=output.get("concerns", []),
        recommendations=output.get("recommendations", []),
    )
