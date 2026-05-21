# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
agents/medical_advisor.py — AI 医疗顾问 Agent（模块 M3）

独立于运动健康三阶段链（Metrics→Data→Coach），
专注于已录入的医疗数据库数据解读和健康建议。

支持四种任务类型：
  - analyze:       综合健康分析（诊断+用药+化验趋势）
  - timeline:      临床事件时间线梳理
  - medications:   用药审查（交互作用+依从性）
  - labs:          化验结果趋势解读

输入约定（input_data）：
  input_data["task_type"]    = analyze | timeline | medications | labs
  input_data["patient"]      = MedPatientProfile 序列化（可选）
  input_data["diagnoses"]    = [MedDiagnosis] 序列化列表
  input_data["events"]       = [MedClinicalEvent] 序列化列表（可选）
  input_data["lab_results"]  = [MedLabResult] 序列化列表（可选）
  input_data["medications"]  = [MedMedication] 序列化列表（可选）

输出格式（AgentResult.output）：
  {
    "summary": str,
    "insights": [str],
    "concerns": [str],
    "recommendations": [str],
    "risk_flags": [str],
  }
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from rhythmind.core.hermes_base import (
    AgentContext,
    AgentResult,
    ComplianceBlockedError,
    HermesBase,
)
from rhythmind.core.memory import MemoryRecallResult

log = structlog.get_logger(__name__)

# 任务类型 → prompt 构建函数映射
TASK_HANDLERS: dict[str, str] = {
    "analyze": "build_analyze_prompt",
    "timeline": "build_timeline_prompt",
    "medications": "build_medications_prompt",
    "labs": "build_labs_prompt",
}


class MedicalAdvisor(HermesBase):
    """
    医疗顾问 Agent。

    读取 med_* 表中的结构化医疗数据，通过 LLM 生成
    健康洞察、风险提示和复诊建议。

    合规约束：
      - 系统提示明确禁止诊断性语言和处方建议
      - 输出通过 ComplianceGate 后置关键词扫描
      - 前置 call_llm() gemma 审查拦截危险意图
    """

    def __init__(self, user_id: str) -> None:
        super().__init__("medical_advisor", user_id)

    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
    ) -> AgentResult:
        bound_log = log.bind(
            agent="medical_advisor", user=ctx.user_id, task=ctx.task_type,
        )

        task = ctx.input_data.get("task_type", "analyze")
        if task not in TASK_HANDLERS:
            task = "analyze"

        patient: dict[str, Any] = ctx.input_data.get("patient", {})
        diagnoses: list[dict] = ctx.input_data.get("diagnoses", [])
        events: list[dict] = ctx.input_data.get("events", [])
        lab_results: list[dict] = ctx.input_data.get("lab_results", [])
        medications: list[dict] = ctx.input_data.get("medications", [])

        prior_summary: dict = memory_ctx.get("last_medical_summary", {}) or {}

        prompt_builder = getattr(self, f"_{TASK_HANDLERS[task]}")
        prompt = prompt_builder(
            patient=patient,
            diagnoses=diagnoses,
            events=events,
            lab_results=lab_results,
            medications=medications,
            prior_summary=prior_summary,
        )

        try:
            raw_json = await self.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是律动 AI 平台的医疗健康顾问，"
                            "具备全科医学知识背景。"
                            "你基于患者的结构化医疗数据提供健康洞察和建议。"
                            "严格禁止：诊断结论、处方建议、具体药物剂量调整。"
                            "使用专业但易懂的语言，重点关注趋势和风险提示。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1024,
            )
            result_data = json.loads(raw_json)
        except ComplianceBlockedError:
            raise
        except Exception as e:
            bound_log.error("medical_advisor llm_error=%s", e)
            result_data = self._fallback_result(task, diagnoses, medications)

        active_diag_count = sum(1 for d in diagnoses if d.get("is_active", True))
        active_med_count = sum(
            1 for m in medications if m.get("status") == "active"
        )
        diag_pen = 0.05 * min(active_diag_count, 4)
        med_pen = 0.03 * min(active_med_count, 6)
        confidence = 0.88 - diag_pen - med_pen
        confidence = max(0.50, confidence)

        return AgentResult(
            output=result_data,
            confidence=confidence,
            skill_candidates=[
                f"medical_{task}",
                f"diagnosis_review_{active_diag_count}active",
            ],
            memory_updates={
                "last_medical_summary": result_data,
                "medical_task_type": task,
                "active_diagnoses_count": active_diag_count,
                "active_medications_count": active_med_count,
            },
            requires_human_review=(
                active_diag_count >= 3
                or any(
                    d.get("diagnosis_type") == "critical" for d in diagnoses
                )
            ),
        )

    # ── Prompt 构建器 ─────────────────────────────────────────────────────────

    @staticmethod
    def _build_analyze_prompt(
        patient: dict,
        diagnoses: list[dict],
        events: list[dict],
        lab_results: list[dict],
        medications: list[dict],
        prior_summary: dict,
    ) -> str:
        diag_lines = "\n".join(
            f"  - {d.get('diagnosis_name', '?')} ({d.get('diagnosis_date', '?')})"
            for d in diagnoses[:20]
        ) or "  （无诊断记录）"

        med_lines = "\n".join(
            f"  - {m.get('medication_name', '?')} {m.get('dose', '')} "
            f"{m.get('frequency', '')}（{m.get('status', '?')}）"
            for m in medications[:20]
        ) or "  （无用药记录）"

        lab_lines = "\n".join(
            f"  - {lr.get('test_name', '?')}: "
            f"{lr.get('value', lr.get('value_str', '?'))} "
            f"{lr.get('unit', '')}（{lr.get('test_date', '?')}）"
            for lr in lab_results[:30]
        ) or "  （无化验结果）"

        prior_str = (
            f"上次分析摘要: {prior_summary.get('summary', '无')}"
            if prior_summary
            else "首次分析"
        )

        return f"""
请基于以下患者医疗数据，进行综合健康分析：

**患者信息**: {patient.get('gender', '?')}性, 出生年份 {patient.get('birth_year', '?')}
**既往诊断**:
{diag_lines}

**当前用药**:
{med_lines}

**近期化验结果**:
{lab_lines}

**历史参考**: {prior_str}

请返回如下 JSON：
{{
  "summary": "一段话健康状态概览",
  "insights": ["洞察1", "洞察2"],
  "concerns": ["需要关注的问题"],
  "recommendations": ["建议1", "建议2"],
  "risk_flags": ["风险标识（如无则空列表）"]
}}

注意：
1. 不得输出诊断结论，仅分析趋势和关联
2. 不得建议具体药物剂量调整
3. 如发现紧急风险，在 risk_flags 中标注"建议尽快就医"
"""

    @staticmethod
    def _build_timeline_prompt(
        patient: dict,
        diagnoses: list[dict],
        events: list[dict],
        lab_results: list[dict],
        medications: list[dict],
        prior_summary: dict,
    ) -> str:
        event_lines = "\n".join(
            f"  - [{e.get('event_date', '?')}] {e.get('event_type', '?')} "
            f"@ {e.get('hospital', '?')} {e.get('department', '')}"
            for e in sorted(events, key=lambda x: str(x.get("event_date", "")))[:50]
        ) or "  （无临床事件）"

        return f"""
请梳理以下患者的临床事件时间线：

**患者**: {patient.get('gender', '?')}性

**临床事件列表**:
{event_lines}

请返回如下 JSON：
{{
  "summary": "时间线概要（50字以内）",
  "insights": ["时间线上的关键发现"],
  "concerns": ["需要持续关注的事件"],
  "recommendations": ["复诊/随访建议"],
  "risk_flags": ["风险标识"]
}}

注意：仅梳理事实，不做诊断推测。
"""

    @staticmethod
    def _build_medications_prompt(
        patient: dict,
        diagnoses: list[dict],
        events: list[dict],
        lab_results: list[dict],
        medications: list[dict],
        prior_summary: dict,
    ) -> str:
        active_meds = [m for m in medications if m.get("status") == "active"]
        past_meds = [m for m in medications if m.get("status") != "active"]

        active_lines = "\n".join(
            f"  - {m.get('medication_name', '?')} {m.get('dose', '')} "
            f"{m.get('route', '')} {m.get('frequency', '')} "
            f"用途: {m.get('purpose', '?')} "
            f"起始: {m.get('start_date', '?')}"
            for m in active_meds
        ) or "  （无当前用药）"

        past_lines = "\n".join(
            f"  - {m.get('medication_name', '?')} {m.get('dose', '')} "
            f"({m.get('start_date', '?')} ~ {m.get('end_date', '?')})"
            for m in past_meds[:10]
        ) or "  （无历史用药）"

        diag_names = ", ".join(
            d.get("diagnosis_name", "?") for d in diagnoses[:10]
        ) or "无"

        return f"""
请审查以下患者的用药情况：

**相关诊断**: {diag_names}

**当前用药**:
{active_lines}

**历史用药**:
{past_lines}

请返回如下 JSON：
{{
  "summary": "用药概况（50字以内）",
  "insights": ["药物关联发现，如潜在的药物相互作用提示"],
  "concerns": ["用药注意事项"],
  "recommendations": ["用药依从性或随访建议"],
  "risk_flags": ["药物相关风险标识"]
}}

注意：
1. 仅提示潜在药物相互作用方向，不做具体调整建议
2. 提醒就诊时携带完整用药清单
3. 如发现严重交互风险，在 risk_flags 中标注"建议咨询药师/医生"
"""

    @staticmethod
    def _build_labs_prompt(
        patient: dict,
        diagnoses: list[dict],
        events: list[dict],
        lab_results: list[dict],
        medications: list[dict],
        prior_summary: dict,
    ) -> str:
        grouped: dict[str, list] = {}
        for lr in lab_results:
            name = lr.get("test_name", "未知")
            grouped.setdefault(name, []).append(lr)

        test_sections = []
        for name, results in grouped.items():
            lines = []
            for r in sorted(results, key=lambda x: str(x.get("test_date", ""))):
                val = r.get("value", r.get("value_str", "?"))
                flag = r.get("flag", "")
                flag_marker = f" [{flag}]" if flag else ""
                date_str = r.get('test_date', '?')
                unit_str = r.get('unit', '')
                lines.append(f"    {date_str}: {val} {unit_str}{flag_marker}")
            ref = results[-1].get('ref_range', '?')
            joined = "\n".join(lines)
            test_sections.append(
                f"  **{name}** (参考范围: {ref}):\n{joined}"
            )

        labs_str = "\n".join(test_sections) or "  （无化验结果）"

        diag_names = ", ".join(
            d.get("diagnosis_name", "?") for d in diagnoses[:5]
        ) or "无"

        return f"""
请解读以下化验结果趋势：

**相关诊断**: {diag_names}

**化验结果**:
{labs_str}

请返回如下 JSON：
{{
  "summary": "化验结果概要（50字以内）",
  "insights": ["趋势分析发现"],
  "concerns": ["异常指标解读"],
  "recommendations": ["复查或随访建议"],
  "risk_flags": ["需紧急关注的指标"]
}}

注意：
1. 分析趋势方向（升高/降低/稳定），不做疾病诊断
2. 异常指标提示参考范围偏差程度
3. 如发现危急值趋势，在 risk_flags 中标注"建议尽快复查"
"""

    @staticmethod
    def _fallback_result(
        task: str,
        diagnoses: list[dict],
        medications: list[dict],
    ) -> dict[str, Any]:
        active_diag = sum(1 for d in diagnoses if d.get("is_active", True))
        active_med = sum(
            1 for m in medications if m.get("status") == "active"
        )
        return {
            "summary": f"医疗{task}服务暂时不可用，已记录当前数据。",
            "insights": [],
            "concerns": [
                f"当前有 {active_diag} 项活跃诊断、"
                f"{active_med} 种在用药物，建议尽快重试。"
            ],
            "recommendations": [
                "请稍后重试，或在就诊时向医生出示完整病历。"
            ],
            "risk_flags": [],
        }
