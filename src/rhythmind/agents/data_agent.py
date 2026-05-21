# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
agents/data_agent.py — AI 数据解读 Agent（模块 M1，重构版）

在 AG2 三级链中，DataAgent 是第二级：
  MetricsAgent（InfluxDB 轨道）→ DataAgent（LLM 解读）→ CoachAgent（训练计划）

职责变化（对比旧版）：
  - 旧版：自己解析指标 + 计算 delta + 调 LLM
  - 新版：直接接收 MetricsAgent 的 MetricsAnalysis 结构体，专注 LLM 深度解读

上游约定（input_data）：
  input_data["metrics_analysis"] = MetricsAgent 的 output dict（MetricsAnalysis）
  input_data["sport_type"]       = 运动类型（可选，兜底 "general"）

输出格式（AgentResult.output）：
  {
    "summary": str,          # 一段话总结
    "highlights": [str],     # 3-5 条核心亮点
    "concerns": [str],       # 需关注的指标
    "metrics_compared": dict # key metric vs 7日均值对比
    "next_suggestion": str,  # 下次训练建议
    "anomaly_digest": str,   # 异常简报（供 CoachAgent 参考）
  }
"""
from __future__ import annotations

import json
from datetime import date
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

# 心率区间参考（5区模型，保留供 prompt 参考）
HR_ZONE_LABELS = {
    "z1": "热身区 (<60% HRmax)",
    "z2": "基础有氧 (60-70%)",
    "z3": "有氧耐力 (70-80%)",
    "z4": "无氧阈 (80-90%)",
    "z5": "最大冲刺 (>90%)",
}


class DataAgent(HermesBase):
    """
    健康数据解读 Agent（重构版）。

    接收 MetricsAgent 的结构化分析结果，专注 LLM 深度解读。
    合规双层防护由基类 HermesBase 自动处理：
      前置：call_llm() 内 gemma-4-e4b 审查
      后置：HermesBase.run() 内 ComplianceGate 扫描
    """

    def __init__(self, user_id: str) -> None:
        super().__init__("data_agent", user_id)

    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
    ) -> AgentResult:
        bound_log = log.bind(agent="data_agent", user=ctx.user_id, task=ctx.task_type)

        # ── 1. 从上游 MetricsAgent 提取分析结果 ──────────────────────────
        analysis: dict[str, Any] = ctx.input_data.get("metrics_analysis", {})
        metrics: dict[str, Any] = analysis.get("metrics", {})
        trends: dict[str, Any] = analysis.get("trends", {})
        anomalies: list[dict] = analysis.get("anomalies", [])
        load_level: str = analysis.get("load_level", "unknown")
        sport_type: str = ctx.input_data.get("sport_type", analysis.get("metrics", {}).get("sport_type", "general"))

        # 无上游分析时降级（独立运行兼容）
        if not metrics:
            bound_log.warning("data_agent no metrics_analysis, using raw input_data")
            metrics = {
                k: ctx.input_data.get(k)
                for k in [
                    "heart_rate_avg", "heart_rate_max", "steps", "distance_km",
                    "calories", "sleep_hours", "hrv",
                ]
            }

        # ── 2. 从 memory 取历史基线（用于叙述对比） ───────────────────────
        baseline: dict[str, Any] = memory_ctx.get("metrics_baseline", {}) or {}

        # ── 3. 构建解读 prompt ────────────────────────────────────────────
        prompt = self._build_prompt(
            metrics=metrics,
            trends=trends,
            anomalies=anomalies,
            load_level=load_level,
            baseline=baseline,
            sport_type=sport_type,
        )

        # ── 5. 通过 call_llm() 生成报告（内含 gemma 前置审查）────────────
        try:
            raw_json = await self.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是律动 AI 健康平台的数据解读专家，"
                            "擅长运动健康数据分析。"
                            "请用简洁、专业、积极的语气回复，"
                            "避免使用医疗诊断性语言。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1024,
            )
            report = json.loads(raw_json)
        except ComplianceBlockedError:
            raise  # 前置审查 BLOCK → 交由 HermesBase.run() 统一处理
        except Exception as e:
            bound_log.error("data_agent llm_error=%s", e)
            report = self._fallback_report(metrics, anomalies)

        # ── 6. 置信度：异常越多置信越低 ──────────────────────────────────
        critical_count = sum(1 for a in anomalies if a.get("severity") == "critical")
        warn_count = sum(1 for a in anomalies if a.get("severity") == "warn")
        base_confidence = 0.92 - 0.20 * critical_count - 0.08 * warn_count
        confidence = max(0.50, base_confidence)

        return AgentResult(
            output=report,
            confidence=confidence,
            skill_candidates=[
                f"report_template_{sport_type}",
                f"hr_zone_analysis_{sport_type}",
            ],
            memory_updates={
                "metrics_baseline": metrics,
                "last_report_date": str(date.today()),
                "sport_type_preference": sport_type,
                "latest_anomalies": anomalies,
            },
            requires_human_review=(
                # critical 级异常 → 触发人工复核
                critical_count > 0
                or (metrics.get("heart_rate_max") or 0) > 195
                or (metrics.get("heart_rate_avg") or 999) < 35
            ),
        )

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(
        metrics: dict[str, Any],
        trends: dict[str, Any],
        anomalies: list[dict],
        load_level: str,
        baseline: dict[str, Any],
        sport_type: str,
    ) -> str:
        # 指标摘要
        metrics_str = "\n".join(
            f"  {k}: {v}" for k, v in metrics.items() if v is not None
        ) or "  （无有效指标）"

        # 7 日趋势摘要
        if trends:
            trend_lines = []
            for f, t in trends.items():
                avg = t.get("avg")
                delta = t.get("delta")
                if avg is not None:
                    delta_str = f"  Δ{delta:+.1f}" if delta is not None else ""
                    trend_lines.append(f"  {f}: 均值 {avg:.1f}{delta_str}")
            trend_str = "\n".join(trend_lines) or "  （暂无趋势数据）"
        else:
            trend_str = "  （InfluxDB 不可用，无趋势数据）"

        # 与历史基线对比（memory 中的上一次基线）
        if baseline:
            delta_lines = []
            for k, v in metrics.items():
                bv = baseline.get(k)
                if isinstance(v, (int, float)) and isinstance(bv, (int, float)):
                    d = round(v - bv, 2)
                    delta_lines.append(f"  {k}: {'+' if d >= 0 else ''}{d}")
            baseline_str = "\n".join(delta_lines) or "  （无差值）"
        else:
            baseline_str = "  （首次上传，无历史对比）"

        # 异常列表
        if anomalies:
            anomaly_lines = [
                f"  {'⛔' if a['severity']=='critical' else '⚠️'} "
                f"{a['field']} = {a['value']} (正常范围 {a['expected']}, {a['severity']})"
                for a in anomalies
            ]
            anomaly_str = "\n".join(anomaly_lines)
        else:
            anomaly_str = "  无异常"

        return f"""
请分析以下运动健康数据并生成 JSON 格式报告：

**运动类型**: {sport_type}
**训练负荷级别**: {load_level}

**本次指标**:
{metrics_str}

**7 日趋势（InfluxDB）**:
{trend_str}

**与上次基线对比（delta）**:
{baseline_str}

**异常检测**:
{anomaly_str}

请返回如下 JSON 结构（所有字段均为中文）：
{{
  "summary": "一段话概括整体状态（50字以内）",
  "highlights": ["亮点1", "亮点2", "亮点3"],
  "concerns": ["关注点1（如有）"],
  "metrics_compared": {{
    "key_metric": {{"current": 数值, "trend_avg": 数值, "trend": "↑/↓/→"}}
  }},
  "next_suggestion": "下次训练建议（一句话）",
  "anomaly_digest": "异常简报（如无异常写'各项指标正常'）"
}}
注意：不得输出诊断结论，不得出现"治疗"、"处方"等医疗术语。
"""

    @staticmethod
    def _fallback_report(
        metrics: dict[str, Any],
        anomalies: list[dict],
    ) -> dict[str, Any]:
        """LLM 调用失败时的降级报告。"""
        return {
            "summary": "数据解读服务暂时不可用，已记录本次数据。",
            "highlights": [],
            "concerns": [
                f"{a['field']} 超出正常范围（{a['severity']}）"
                for a in anomalies
            ],
            "metrics_compared": {},
            "next_suggestion": "请稍后重试，或查看历史趋势图。",
            "anomaly_digest": (
                f"发现 {len(anomalies)} 项异常" if anomalies else "各项指标正常"
            ),
        }
