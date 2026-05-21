"""
db/medical_models.py — 医疗数据 SQLAlchemy ORM 模型

5 张表：
  MedPatientProfile  — 患者画像（脱敏）
  MedDiagnosis       — 诊断记录
  MedClinicalEvent   — 统一事件时间线
  MedLabResult       — 化验结果
  MedMedication      — 用药记录
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TEXT, TypeDecorator

from rhythmind.core.memory.models import Base, JSONText


def _json(default: Any = None) -> Any:
    return JSONB(none_as_null=True).with_variant(JSONText(), "sqlite")


class MedPatientProfile(Base):
    __tablename__ = "med_patient_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    gender: Mapped[str] = mapped_column(String(8), nullable=False)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blood_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    insurance_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insurance_id_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address_region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    demographics: Mapped[Any] = mapped_column(
        "demographics", _json(), nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    def __repr__(self) -> str:
        return f"<MedPatientProfile user={self.user_id} gender={self.gender}>"


class MedDiagnosis(Base):
    __tablename__ = "med_diagnosis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    diagnosis_date: Mapped[date] = mapped_column(Date, nullable=False)
    diagnosis_name: Mapped[str] = mapped_column(String(256), nullable=False)
    diagnosis_type: Mapped[str] = mapped_column(String(32), nullable=False)
    icd_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    hospital: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[Any] = mapped_column(
        "metadata", _json(), nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_med_diag_user_date", "user_id", "diagnosis_date"),
        Index("ix_med_diag_active", "user_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<MedDiagnosis {self.diagnosis_name} date={self.diagnosis_date}>"


class MedClinicalEvent(Base):
    __tablename__ = "med_clinical_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    insurance_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    details: Mapped[Any] = mapped_column(
        "details", _json(), nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_med_event_user_date", "user_id", "event_date"),
        Index("ix_med_event_type", "user_id", "event_type"),
    )

    def __repr__(self) -> str:
        return f"<MedClinicalEvent {self.event_type} date={self.event_date}>"


class MedLabResult(Base):
    __tablename__ = "med_lab_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    test_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_str: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    flag: Mapped[str | None] = mapped_column(String(8), nullable=True)
    specimen: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hospital: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_: Mapped[Any] = mapped_column(
        "metadata", _json(), nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_med_lab_user_test", "user_id", "test_name", "test_date"),
        Index("ix_med_lab_date", "user_id", "test_date"),
    )

    def __repr__(self) -> str:
        return f"<MedLabResult {self.test_name}={self.value} {self.unit}>"


class MedMedication(Base):
    __tablename__ = "med_medication"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    medication_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dose: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    prescriber: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hospital: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_: Mapped[Any] = mapped_column(
        "metadata", _json(), nullable=False, default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    __table_args__ = (
        Index("ix_med_med_user_status", "user_id", "status"),
        Index("ix_med_med_name", "user_id", "medication_name"),
    )

    def __repr__(self) -> str:
        return f"<MedMedication {self.medication_name} status={self.status}>"
