"""
tests/unit/test_medical_models.py — 医疗 ORM 模型 CRUD 测试

覆盖 5 张医疗表：MedPatientProfile, MedDiagnosis, MedClinicalEvent,
MedLabResult, MedMedication。使用 SQLite in-memory（conftest reset_db）。
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

import rhythmind.core.memory.manager as mem_manager
from rhythmind.db.medical_models import (
    MedClinicalEvent,
    MedDiagnosis,
    MedLabResult,
    MedMedication,
    MedPatientProfile,
)


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ── MedPatientProfile ────────────────────────────────────────────────────


class TestMedPatientProfile:

    @pytest.mark.asyncio
    async def test_create_and_query(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            profile = MedPatientProfile(
                user_id=user_id,
                gender="male",
                birth_year=1990,
                blood_type="A+",
            )
            s.add(profile)
            await s.commit()
            await s.refresh(profile)

            assert profile.id is not None
            assert profile.gender == "male"
            assert profile.birth_year == 1990
            assert profile.demographics == {}
            assert "MedPatientProfile" in repr(profile)

    @pytest.mark.asyncio
    async def test_optional_fields_default_null(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            profile = MedPatientProfile(user_id=user_id, gender="female")
            s.add(profile)
            await s.commit()
            await s.refresh(profile)

            assert profile.insurance_type is None
            assert profile.insurance_id_hash is None
            assert profile.address_region is None
            assert profile.blood_type is None

    @pytest.mark.asyncio
    async def test_demographics_jsonb(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            demo = {"allergies": ["penicillin"], "height_cm": 175}
            profile = MedPatientProfile(
                user_id=user_id, gender="male", demographics=demo,
            )
            s.add(profile)
            await s.commit()
            await s.refresh(profile)

            assert profile.demographics == demo

    @pytest.mark.asyncio
    async def test_created_at_auto_set(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            profile = MedPatientProfile(user_id=user_id, gender="male")
            s.add(profile)
            await s.commit()
            await s.refresh(profile)

            assert profile.created_at is not None
            assert profile.updated_at is not None


# ── MedDiagnosis ─────────────────────────────────────────────────────────


class TestMedDiagnosis:

    @pytest.mark.asyncio
    async def test_create_and_query(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            diag = MedDiagnosis(
                user_id=user_id,
                diagnosis_date=date(2026, 1, 15),
                diagnosis_name="高血压",
                diagnosis_type="chronic",
                icd_code="I10",
                hospital="北京协和",
            )
            s.add(diag)
            await s.commit()
            await s.refresh(diag)

            assert diag.id is not None
            assert diag.is_active is True
            assert diag.metadata_ == {}
            assert "高血压" in repr(diag)

    @pytest.mark.asyncio
    async def test_inactive_diagnosis(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            diag = MedDiagnosis(
                user_id=user_id,
                diagnosis_date=date(2025, 6, 1),
                diagnosis_name="感冒",
                diagnosis_type="acute",
                is_active=False,
            )
            s.add(diag)
            await s.commit()
            await s.refresh(diag)

            assert diag.is_active is False

    @pytest.mark.asyncio
    async def test_multiple_diagnoses_order(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            for i, name in enumerate(["高血压", "糖尿病", "高血脂"]):
                s.add(MedDiagnosis(
                    user_id=user_id,
                    diagnosis_date=date(2026, 1, i + 1),
                    diagnosis_name=name,
                    diagnosis_type="chronic",
                ))
            await s.commit()

            result = await s.execute(
                select(MedDiagnosis)
                .where(MedDiagnosis.user_id == user_id)
                .order_by(MedDiagnosis.diagnosis_date.desc())
            )
            all_diags = result.scalars().all()
            assert len(all_diags) == 3
            assert all_diags[0].diagnosis_name == "高血脂"


# ── MedClinicalEvent ────────────────────────────────────────────────────


class TestMedClinicalEvent:

    @pytest.mark.asyncio
    async def test_create_hospitalization(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            event = MedClinicalEvent(
                user_id=user_id,
                event_date=_dt(2026, 3, 10),
                event_type="hospitalization",
                hospital="北医三院",
                department="骨科",
                duration_days=5,
                cost=15000.0,
            )
            s.add(event)
            await s.commit()
            await s.refresh(event)

            assert event.event_type == "hospitalization"
            assert event.duration_days == 5
            assert event.cost == 15000.0
            assert event.details == {}
            assert "hospitalization" in repr(event)

    @pytest.mark.asyncio
    async def test_create_lab_visit(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            event = MedClinicalEvent(
                user_id=user_id,
                event_date=_dt(2026, 4, 20),
                event_type="lab_test",
                hospital="体检中心",
                details={"tests": ["血常规", "肝功能"]},
            )
            s.add(event)
            await s.commit()
            await s.refresh(event)

            assert event.details["tests"] == ["血常规", "肝功能"]

    @pytest.mark.asyncio
    async def test_filter_by_event_type(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            for etype in ["hospitalization", "lab_test", "follow_up"]:
                s.add(MedClinicalEvent(
                    user_id=user_id,
                    event_date=_dt(2026, 1, 1),
                    event_type=etype,
                ))
            await s.commit()

            result = await s.execute(
                select(MedClinicalEvent).where(
                    MedClinicalEvent.user_id == user_id,
                    MedClinicalEvent.event_type == "lab_test",
                )
            )
            labs = result.scalars().all()
            assert len(labs) == 1
            assert labs[0].event_type == "lab_test"


# ── MedLabResult ────────────────────────────────────────────────────────


class TestMedLabResult:

    @pytest.mark.asyncio
    async def test_create_numeric_result(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            lab = MedLabResult(
                user_id=user_id,
                test_date=_dt(2026, 2, 15),
                test_name="空腹血糖",
                value=5.6,
                unit="mmol/L",
                ref_range="3.9-6.1",
                flag="normal",
            )
            s.add(lab)
            await s.commit()
            await s.refresh(lab)

            assert lab.value == 5.6
            assert lab.flag == "normal"
            assert "空腹血糖" in repr(lab)

    @pytest.mark.asyncio
    async def test_create_text_result(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            lab = MedLabResult(
                user_id=user_id,
                test_date=_dt(2026, 2, 15),
                test_name="血型鉴定",
                value_str="A型Rh阳性",
                specimen="全血",
            )
            s.add(lab)
            await s.commit()
            await s.refresh(lab)

            assert lab.value is None
            assert lab.value_str == "A型Rh阳性"

    @pytest.mark.asyncio
    async def test_abnormal_flag(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            lab = MedLabResult(
                user_id=user_id,
                test_date=_dt(2026, 3, 1),
                test_name="糖化血红蛋白",
                value=7.8,
                unit="%",
                ref_range="<6.5",
                flag="high",
            )
            s.add(lab)
            await s.commit()
            await s.refresh(lab)

            assert lab.flag == "high"

    @pytest.mark.asyncio
    async def test_trend_query(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            for i, val in enumerate([5.2, 5.4, 5.6, 5.8]):
                s.add(MedLabResult(
                    user_id=user_id,
                    test_date=_dt(2026, i + 1, 1),
                    test_name="空腹血糖",
                    value=val,
                    unit="mmol/L",
                ))
            await s.commit()

            result = await s.execute(
                select(MedLabResult)
                .where(
                    MedLabResult.user_id == user_id,
                    MedLabResult.test_name == "空腹血糖",
                )
                .order_by(MedLabResult.test_date)
            )
            labs = result.scalars().all()
            assert len(labs) == 4
            values = [l.value for l in labs]
            assert values == [5.2, 5.4, 5.6, 5.8]


# ── MedMedication ───────────────────────────────────────────────────────


class TestMedMedication:

    @pytest.mark.asyncio
    async def test_create_active_medication(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            med = MedMedication(
                user_id=user_id,
                medication_name="阿司匹林",
                dose="100mg",
                route="oral",
                frequency="每日一次",
                purpose="抗血小板",
                start_date=date(2026, 1, 1),
                prescriber="张医生",
            )
            s.add(med)
            await s.commit()
            await s.refresh(med)

            assert med.status == "active"
            assert med.end_date is None
            assert "阿司匹林" in repr(med)

    @pytest.mark.asyncio
    async def test_discontinued_medication(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            med = MedMedication(
                user_id=user_id,
                medication_name="头孢",
                dose="500mg",
                route="oral",
                frequency="每日三次",
                start_date=date(2025, 12, 1),
                end_date=date(2025, 12, 7),
                status="discontinued",
            )
            s.add(med)
            await s.commit()
            await s.refresh(med)

            assert med.status == "discontinued"
            assert med.end_date == date(2025, 12, 7)

    @pytest.mark.asyncio
    async def test_filter_active(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            for name, status in [
                ("阿司匹林", "active"), ("头孢", "discontinued"),
            ]:
                s.add(MedMedication(
                    user_id=user_id,
                    medication_name=name,
                    dose="100mg",
                    start_date=date(2026, 1, 1),
                    status=status,
                ))
            await s.commit()

            result = await s.execute(
                select(MedMedication).where(
                    MedMedication.user_id == user_id,
                    MedMedication.status == "active",
                )
            )
            active = result.scalars().all()
            assert len(active) == 1
            assert active[0].medication_name == "阿司匹林"

    @pytest.mark.asyncio
    async def test_metadata_jsonb(self, user_id):
        async with mem_manager.AsyncSessionLocal() as s:
            meta = {"side_effects": ["胃不适"], "note": "饭后服用"}
            med = MedMedication(
                user_id=user_id,
                medication_name="阿司匹林",
                dose="100mg",
                start_date=date(2026, 1, 1),
                metadata_=meta,
            )
            s.add(med)
            await s.commit()
            await s.refresh(med)

            assert med.metadata_["side_effects"] == ["胃不适"]
