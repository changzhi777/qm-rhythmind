# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
agents/metrics_agent.py — MetricsProcessor：纯规则引擎（无 LLM，无 HermesBase）

职责：
  1. 将本次健康指标写入 InfluxDB time-series
  2. 查询 7 日趋势（TrendSeries → 趋势摘要）
  3. 规则引擎：异常检测 + 训练负荷分级
  4. 输出 MetricsAnalysis 结构体，供下游 DataAgent / CoachAgent 使用

设计约束：
  - 无 LLM 调用（纯数值处理，低延迟）
  - 不继承 HermesBase（无 call_llm、无 prompt 审查、无 MemoryManager 开销）
  - InfluxDB 不可用 → 降级（仅用 input_data 原始数据），不中断链路
  - 输出置信度固定 1.0（纯规则，无随机性）
  - 返回 HermesRunResult 保持与 SwarmDataCoach 的兼容性

MetricsAnalysis 输出格式（HermesRunResult.output）：
  {
    "user_id": str,
    "timestamp": str,
    "metrics": dict,
    "trends": {
      "<field>": {
        "avg": float, "latest": float, "oldest": float,
        "delta": float | None, "points": int,
      }
    },
    "anomalies": [
      {"field": str, "value": float,
       "expected": str, "severity": "warn"|"critical"}
    ],
    "load_level": str,
    "write_ok": bool,
    "influx_available": bool
  }
"""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import structlog

from rhythmind.adapters.influx_client import (
    InfluxClient,
    InfluxUnavailableError,
    MetricPoint,
)
from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult
from rhythmind.core.hermes_base import AgentContext, HermesRunResult

log = structlog.get_logger(__name__)

# ── 异常阈值（规则引擎）────────────────────────────────────────────────────────

_ANOMALY_RULES: dict[str, dict[str, Any]] = {
    "heart_rate_avg": {
        "min": 40, "max": 120, "critical_min": 30, "critical_max": 150,
    },
    "heart_rate_max": {
        "min": 50, "max": 200, "critical_min": 40, "critical_max": 220,
    },
    "sleep_hours": {
        "min": 4, "max": 12, "critical_min": 2, "critical_max": 16,
    },
    "hrv": {
        "min": 10, "max": 200, "critical_min": 5, "critical_max": 300,
    },
    "body_fat_pct": {
        "min": 3, "max": 45, "critical_min": 2, "critical_max": 55,
    },
    "water_pct": {
        "min": 40, "max": 80, "critical_min": 30, "critical_max": 90,
    },
    "visceral_fat":    {"min": 1,   "max": 15,  "critical_min": 1,  "critical_max": 30},
}

# 7 日训练量（距离 km）→ 负荷级别
_LOAD_THRESHOLDS = [
    (0,   5,   "very_low"),
    (5,   20,  "low"),
    (20,  50,  "moderate"),
    (50,  80,  "high"),
    (80,  1e9, "very_high"),
]

# 查询趋势的字段列表
_TREND_FIELDS = [
    "heart_rate_avg", "heart_rate_max",
    "steps", "distance_km", "calories",
    "sleep_hours", "hrv",
]

# 写入 InfluxDB 的 fields 集合
_WRITE_FIELDS = [
    "heart_rate_avg", "heart_rate_max", "steps", "distance_km", "calories",
    "sleep_hours", "hrv", "body_fat_pct", "muscle_mass_kg", "water_pct", "visceral_fat",
]


class MetricsProcessor:
    """
    纯数值处理的 InfluxDB 轨道处理器。

    不继承 HermesBase（无 LLM、无 prompt 审查、无 MemoryManager）。
    返回 HermesRunResult 保持 SwarmDataCoach 兼容性。
    """

    def __init__(self, user_id: str, influx: InfluxClient | None = None) -> None:
        self.user_id = user_id
        self._influx = influx or InfluxClient()
        self._log = log.bind(agent="metrics_processor", user_id=user_id)

    async def run(self, ctx: AgentContext) -> HermesRunResult:
        """执行指标分析，返回 HermesRunResult。"""
        t0 = time.perf_counter()
        bound_log = self._log.bind(session=ctx.session_id, task=ctx.task_type)

        metrics = self._parse_metrics(ctx.input_data)
        source = ctx.input_data.get("source", "manual")
        sport_type = ctx.input_data.get("sport_type", "general")
        now_utc = datetime.now(tz=UTC)

        # ── 1. 写入 InfluxDB ──────────────────────────────────────────────
        write_ok = False
        influx_available = True
        try:
            point = MetricPoint(
                user_id=ctx.user_id,
                source=source,
                sport_type=sport_type,
                fields={
                    k: metrics[k]
                    for k in _WRITE_FIELDS
                    if metrics.get(k) is not None
                },
                ts=now_utc,
            )
            write_ok = await self._influx.write_metrics(point)
            bound_log.debug("metrics.write ok=%s", write_ok)
        except InfluxUnavailableError:
            influx_available = False
            bound_log.warning("metrics.influx_unavailable fallback=no_write")
        except Exception as e:
            bound_log.error("metrics.write_error=%s", e)

        # ── 2. 查询 7 日趋势 ──────────────────────────────────────────────
        trends: dict[str, Any] = {}
        if influx_available:
            try:
                raw_trends = await self._influx.query_range(
                    user_id=ctx.user_id,
                    fields=_TREND_FIELDS,
                    start="-7d",
                    aggregation_window="1d",
                    fn="mean",
                )
                for field_name, series in raw_trends.items():
                    trends[field_name] = {
                        "avg": series.avg,
                        "latest": series.latest,
                        "oldest": series.oldest,
                        "delta": series.delta,
                        "points": len(series.values),
                    }
                bound_log.debug("metrics.trends fields=%s", list(trends.keys()))
            except InfluxUnavailableError:
                influx_available = False
                bound_log.warning("metrics.influx_unavailable fallback=no_trends")
            except Exception as e:
                bound_log.error("metrics.query_range_error=%s", e)

        # ── 3. 异常检测（规则引擎）────────────────────────────────────────
        anomalies = self._detect_anomalies(metrics)

        # ── 4. 训练负荷分级 ───────────────────────────────────────────────
        distance_7d: float = 0.0
        if "distance_km" in trends and trends["distance_km"]["avg"] is not None:
            distance_7d = trends["distance_km"]["avg"] * 7
        elif metrics.get("distance_km") is not None:
            distance_7d = float(metrics["distance_km"])

        load_level = self._classify_load(distance_7d)
        bound_log.debug("metrics.load dist7d=%.1f level=%s", distance_7d, load_level)

        # ── 5. 构造结果 ────────────────────────────────────────────────────
        analysis: dict[str, Any] = {
            "user_id": ctx.user_id,
            "timestamp": now_utc.isoformat(),
            "metrics": metrics,
            "trends": trends,
            "anomalies": anomalies,
            "load_level": load_level,
            "write_ok": write_ok,
            "influx_available": influx_available,
        }

        has_critical = any(a["severity"] == "critical" for a in anomalies)
        latency_ms = (time.perf_counter() - t0) * 1000

        # 纯规则引擎：直接构造 PASS ComplianceResult（confidence=1.0）
        compliance = ComplianceResult(
            level=ComplianceLevel.PASS,
            output=analysis,
            confidence=1.0,
            skill_candidates=[
                f"metrics_baseline_{sport_type}",
                "anomaly_rule_v1",
            ],
            memory_updates={
                "last_metrics_ts": now_utc.isoformat(),
                "last_load_level": load_level,
                "latest_anomalies_count": len(anomalies),
            },
            advisor_review=has_critical,
        )

        # ── 6. 持久化 memory_updates ─────────────────────────────────────
        # MetricsProcessor 不继承 HermesBase，因此 compliance.memory_updates
        # 不会被 HermesBase.run() 自动消费。显式调用 MemoryManager.update()
        # 写库，失败不阻断主流程（仅记录日志）。
        if compliance.memory_updates:
            try:
                from rhythmind.core.memory import MemoryManager

                mm = MemoryManager(self.user_id, agent="metrics_processor")
                await mm.update(compliance.memory_updates)
            except Exception as mem_exc:
                bound_log.warning(
                    "metrics.memory_persist_skipped error=%s", mem_exc
                )

        return HermesRunResult(
            compliance=compliance,
            agent="metrics_processor",
            user_id=self.user_id,
            task_type=ctx.task_type,
            latency_ms=latency_ms,
        )

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_metrics(raw: dict[str, Any]) -> dict[str, Any]:
        """提取并类型化健康指标，缺失字段填 None。"""
        fields = [
            "heart_rate_avg", "heart_rate_max", "heart_rate_zones",
            "steps", "distance_km", "calories",
            "sleep_hours", "hrv",
            "body_fat_pct", "muscle_mass_kg", "water_pct", "visceral_fat",
        ]
        parsed = {}
        for f in fields:
            v = raw.get(f)
            if v is not None:
                try:
                    parsed[f] = float(v) if f != "heart_rate_zones" else v
                except (TypeError, ValueError):
                    parsed[f] = v
            else:
                parsed[f] = None
        return parsed

    @staticmethod
    def _detect_anomalies(metrics: dict[str, Any]) -> list[dict[str, Any]]:
        """规则引擎：对比 _ANOMALY_RULES，输出异常列表。"""
        anomalies = []
        for field_name, rule in _ANOMALY_RULES.items():
            val = metrics.get(field_name)
            if val is None or not isinstance(val, (int, float)):
                continue
            val = float(val)

            if val < rule["critical_min"] or val > rule["critical_max"]:
                severity = "critical"
            elif val < rule["min"] or val > rule["max"]:
                severity = "warn"
            else:
                continue

            anomalies.append({
                "field": field_name,
                "value": val,
                "expected": f"[{rule['min']}, {rule['max']}]",
                "severity": severity,
            })
        return anomalies

    @staticmethod
    def _classify_load(distance_7d: float) -> str:
        """将 7 日累计距离映射为训练负荷级别。"""
        for low, high, label in _LOAD_THRESHOLDS:
            if low <= distance_7d < high:
                return label
        return "very_high"


# 向后兼容别名（供 tests 和外部导入逐步迁移）
MetricsAgent = MetricsProcessor
