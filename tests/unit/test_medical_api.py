"""
tests/unit/test_medical_api.py — Medical API Router 单元测试

覆盖 4 个端点：
  POST /medical/analyze    — 综合健康分析
  GET  /medical/timeline   — 临床事件时间线
  GET  /medical/medications — 用药列表
  GET  /medical/labs/{test} — 化验结果趋势

Mock MedicalAdvisor.run() 返回固定结果，隔离 LLM 依赖。
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from rhythmind.api.main import app
from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult
from rhythmind.core.hermes_base import HermesRunResult


def _make_run_result(
    output: dict | None = None,
    success: bool = True,
    confidence: float = 0.85,
) -> HermesRunResult:
    return HermesRunResult(
        compliance=ComplianceResult(
            level=ComplianceLevel.PASS if success else ComplianceLevel.BLOCK,
            output=output or {},
            confidence=confidence,
        ),
        agent="medical_advisor",
        user_id="test_user",
        task_type="medical_test",
        latency_ms=100.0,
    )


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def _setup_patient(user_id: str) -> None:
    import rhythmind.core.memory.manager as mem_manager
    from rhythmind.db.medical_models import MedPatientProfile

    async with mem_manager.AsyncSessionLocal() as s:
        s.add(MedPatientProfile(
            user_id=user_id, gender="male", birth_year=1990,
            blood_type="A+", demographics={"height_cm": 175},
        ))
        await s.commit()


async def _setup_diagnoses(user_id: str) -> None:
    import rhythmind.core.memory.manager as mem_manager
    from rhythmind.db.medical_models import MedDiagnosis

    async with mem_manager.AsyncSessionLocal() as s:
        s.add(MedDiagnosis(
            user_id=user_id,
            diagnosis_date=date(2026, 1, 15),
            diagnosis_name="高血压",
            diagnosis_type="chronic",
            icd_code="I10",
            is_active=True,
        ))
        await s.commit()


async def _setup_events(user_id: str) -> None:
    import rhythmind.core.memory.manager as mem_manager
    from rhythmind.db.medical_models import MedClinicalEvent

    async with mem_manager.AsyncSessionLocal() as s:
        s.add(MedClinicalEvent(
            user_id=user_id,
            event_date=_dt(2026, 3, 10),
            event_type="hospitalization",
            hospital="北医三院",
            department="骨科",
            duration_days=5,
            cost=15000.0,
        ))
        await s.commit()


async def _setup_medications(user_id: str) -> None:
    import rhythmind.core.memory.manager as mem_manager
    from rhythmind.db.medical_models import MedMedication

    async with mem_manager.AsyncSessionLocal() as s:
        s.add(MedMedication(
            user_id=user_id,
            medication_name="阿司匹林",
            dose="100mg",
            route="oral",
            frequency="每日一次",
            start_date=date(2026, 1, 1),
            status="active",
        ))
        await s.commit()


async def _setup_lab_results(user_id: str) -> None:
    import rhythmind.core.memory.manager as mem_manager
    from rhythmind.db.medical_models import MedLabResult

    async with mem_manager.AsyncSessionLocal() as s:
        for i, val in enumerate([5.2, 5.4, 5.6]):
            s.add(MedLabResult(
                user_id=user_id,
                test_date=_dt(2026, i + 1, 1),
                test_name="空腹血糖",
                value=val,
                unit="mmol/L",
                flag="normal" if val < 5.5 else "high",
            ))
        await s.commit()


# ── POST /medical/analyze ────────────────────────────────────────────────


class TestAnalyzeEndpoint:

    @pytest.mark.asyncio
    async def test_analyze_success(self, user_id):
        await _setup_patient(user_id)
        await _setup_diagnoses(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                output={
                    "summary": "患者整体健康状态稳定",
                    "insights": ["血压控制良好"],
                    "concerns": [],
                    "recommendations": ["继续保持运动"],
                    "risk_flags": [],
                },
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/medical/analyze",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["summary"] == "患者整体健康状态稳定"
            assert "血压控制良好" in data["insights"]
            assert data["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_analyze_no_data(self, user_id):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/medical/analyze",
                headers={"Authorization": f"Bearer {user_id}"},
            )

        assert resp.status_code == 404
        assert "未找到" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_analyze_compliance_fail(self, user_id):
        await _setup_patient(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                success=False, output={"error": "合规检查未通过"},
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v1/medical/analyze",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 422


# ── GET /medical/timeline ────────────────────────────────────────────────


class TestTimelineEndpoint:

    @pytest.mark.asyncio
    async def test_timeline_success(self, user_id):
        await _setup_patient(user_id)
        await _setup_events(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                output={
                    "summary": "1次住院记录",
                    "insights": ["骨折术后恢复"],
                    "recommendations": ["定期复查"],
                },
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/medical/timeline",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert len(data["events"]) == 1
            assert data["events"][0]["event_type"] == "hospitalization"
            assert data["summary"] == "1次住院记录"

    @pytest.mark.asyncio
    async def test_timeline_no_events(self, user_id):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/medical/timeline",
                headers={"Authorization": f"Bearer {user_id}"},
            )

        assert resp.status_code == 404


# ── GET /medical/medications ─────────────────────────────────────────────


class TestMedicationsEndpoint:

    @pytest.mark.asyncio
    async def test_medications_success(self, user_id):
        await _setup_patient(user_id)
        await _setup_medications(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                output={
                    "summary": "1种活跃用药",
                    "insights": ["阿司匹林常规剂量"],
                    "concerns": [],
                    "recommendations": ["注意胃部不适"],
                },
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/medical/medications",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert len(data["medications"]) == 1
            assert data["medications"][0]["medication_name"] == "阿司匹林"

    @pytest.mark.asyncio
    async def test_medications_no_data(self, user_id):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/medical/medications",
                headers={"Authorization": f"Bearer {user_id}"},
            )

        assert resp.status_code == 404


# ── GET /medical/labs/{test} ─────────────────────────────────────────────


class TestLabsEndpoint:

    @pytest.mark.asyncio
    async def test_labs_success(self, user_id):
        await _setup_patient(user_id)
        await _setup_lab_results(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                output={
                    "summary": "血糖呈上升趋势",
                    "insights": ["最近一次偏高"],
                    "concerns": ["需关注糖尿病风险"],
                    "recommendations": ["控制碳水摄入"],
                },
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/medical/labs/空腹血糖",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["test_name"] == "空腹血糖"
            assert len(data["results"]) == 3
            assert data["summary"] == "血糖呈上升趋势"

    @pytest.mark.asyncio
    async def test_labs_no_data(self, user_id):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
        ) as client:
            resp = await client.get(
                "/api/v1/medical/labs/不存在的检查",
                headers={"Authorization": f"Bearer {user_id}"},
            )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_labs_limit_param(self, user_id):
        await _setup_patient(user_id)
        await _setup_lab_results(user_id)

        with patch(
            "rhythmind.api.routers.medical.MedicalAdvisor"
        ) as MockAdvisor:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=_make_run_result(
                output={"summary": "", "insights": [], "concerns": [], "recommendations": []},  # noqa: E501
            ))
            MockAdvisor.return_value = mock_instance

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/v1/medical/labs/空腹血糖?limit=2",
                    headers={"Authorization": f"Bearer {user_id}"},
                )

            assert resp.status_code == 200
            assert len(resp.json()["results"]) == 2
