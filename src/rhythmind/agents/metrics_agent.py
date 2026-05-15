# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
agents/metrics_agent.py — InfluxDB 轨道 Agent（无 LLM）

职责：
  1. 将本次健康指标写入 InfluxDB time-series
  2. 查询 7 日趋势（TrendSeries → 趋势摘要）
  3. 规则引擎：异常检测 + 训练负荷分级
  4. 输出 MetricsAnalysis 结构体，供下游 DataAgent / CoachAgent 使用

设计约束：
  - 无 LLM 调用（纯数值处理，低延迟）
  - InfluxDB 不可用 → 降级（仅用 input_data 原始数据），不中断链路
  - 输出置信度固定 1.0（纯规则，无随机性）
  - 不依赖 HermesBase.call_llm()，不触发 gemma 审查

MetricsAnalysis 输出格式（AgentResult.output）：
  {
    "user_id": str,
    "timestamp": str,                # ISO8601 UTC
    "metrics": dict,                 # 本次原始指标
    "trends": {                      # 7 日趋势摘要（InfluxDB 返回为空时为 {}）
      "<field>": {
        "avg": float,
        "latest": float,
        "oldest": float,
        "delta": float | None,
        "points": int
      }
    },
    "anomalies": [                   # 规则引擎检出的异常
      {"field": str, "value": float, "expected": str, "severity": "warn"|"critical"}
    ],
    "load_level": str,               # very_low | low | moderate | high | very_high
    "write_ok": bool,                # InfluxDB 写入是否成功
    "influx_available": bool         # InfluxDB 是否可达
  }
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from rhythmind.adapters.influx_client import (
    InfluxClient,
    InfluxUnavailableError,
    MetricPoint,
)
from rhythmind.core.hermes_base import AgentContext, AgentResult, HermesBase
from rhythmind.core.memory import MemoryRecallResult

log = structlog.get_logger(__name__)

# ── 异常阈值（规则引擎）────────────────────────────────────────────────────────

_ANOMALY_RULES: dict[str, dict[str, Any]] = {
    "heart_rate_avg":  {"min": 40,  "max": 120, "critical_min": 30, "critical_max": 150},
    "heart_rate_max":  {"min": 50,  "max": 200, "critical_min": 40, "critical_max": 220},
    "sleep_hours":     {"min": 4,   "max": 12,  "critical_min": 2,  "critical_max": 16},
    "hrv":             {"min": 10,  "max": 200, "critical_min": 5,  "critical_max": 300},
    "body_fat_pct":    {"min": 3,   "max": 45,  "critical_min": 2,  "critical_max": 55},
    "water_pct":       {"min": 40,  "max": 80,  "critical_min": 30, "critical_max": 90},
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

# MetricsAgent 写入 InfluxDB 的 fields 集合
_WRITE_FIELDS = [
    "heart_rate_avg", "heart_rate_max", "steps", "distance_km", "calories",
    "sleep_hours", "hrv", "body_fat_pct", "muscle_mass_kg", "water_pct", "visceral_fat",
]


class MetricsAgent(HermesBase):
    """
    纯数值处理的 InfluxDB 轨道 Agent。

    继承 HermesBase（获得 memory、skill、compliance 闭环），
    但 execute() 内不调用 LLM，所有逻辑为规则引擎。
    """

    def __init__(self, user_id: str, influx: InfluxClient | None = None) -> None:
        super().__init__("metrics_agent", user_id)
        # 允许外部注入（测试 mock），否则用默认实例
        self._influx = influx or InfluxClient()

    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
        skill_ctx: list[dict[str, Any]],
    ) -> AgentResult:
        bound_log = log.bind(agent="metrics_agent", user=ctx.user_id)

        # ── 1. 解析原始指标 ───────────────────────────────────────────────
        metrics = self._parse_metrics(ctx.input_data)
        source = ctx.input_data.get("source", "manual")
        sport_type = ctx.input_data.get("sport_type", "general")
        now_utc = datetime.now(tz=UTC)

        # ── 2. 写入 InfluxDB ──────────────────────────────────────────────
        write_ok = False
        influx_available = True
        try:
            point = MetricPoint(
                user_id=ctx.user_id,
                source=source,
                sport_type=sport_type,
                fields={k: metrics[k] for k in _WRITE_FIELDS if metrics.get(k) is not None},
                ts=now_utc,
            )
            write_ok = await self._influx.write_metrics(point)
            bound_log.debug("metrics_agent.write ok=%s", write_ok)
        except InfluxUnavailableError:
            influx_available = False
            bound_log.warning("metrics_agent.influx_unavailable fallback=no_write")
        except Exception as e:
            bound_log.error("metrics_agent.write_error=%s", e)

        # ── 3. 查询 7 日趋势 ──────────────────────────────────────────────
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
                # 将 TrendSeries 转为可序列化的 dict
                for field_name, series in raw_trends.items():
                    trends[field_name] = {
                        "avg": series.avg,
                        "latest": series.latest,
                        "oldest": series.oldest,
                        "delta": series.delta,
                        "points": len(series.values),
                    }
                bound_log.debug(
                    "metrics_agent.trends fields=%s", list(trends.keys())
                )
            except InfluxUnavailableError:
                influx_available = False
                bound_log.warning("metrics_agent.influx_unavailable fallback=no_trends")
            except Exception as e:
                bound_log.error("metrics_agent.query_range_error=%s", e)

        # ── 4. 异常检测（规则引擎）────────────────────────────────────────
        anomalies = self._detect_anomalies(metrics)

        # ── 5. 训练负荷分级 ───────────────────────────────────────────────
        # 优先用 7 日趋势累计距离；回退到本次单次距离
        distance_7d: float = 0.0
        if "distance_km" in trends and trends["distance_km"]["avg"] is not None:
            # avg per day × 7 ≈ weekly volume (粗估)
            distance_7d = trends["distance_km"]["avg"] * 7
        elif metrics.get("distance_km") is not None:
            distance_7d = float(metrics["distance_km"])

        load_level = self._classify_load(distance_7d)
        bound_log.debug("metrics_agent.load dist7d=%.1f level=%s", distance_7d, load_level)

        # ── 6. 构造 MetricsAnalysis 输出 ──────────────────────────────────
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

        # 有 critical 异常 → 请求人工复核
        has_critical = any(a["severity"] == "critical" for a in anomalies)

        return AgentResult(
            output=analysis,
            confidence=1.0,   # 纯规则，无随机性
            skill_candidates=[
                f"metrics_baseline_{sport_type}",
                "anomaly_rule_v1",
            ],
            memory_updates={
                "last_metrics_ts": now_utc.isoformat(),
                "last_load_level": load_level,
                "latest_anomalies_count": len(anomalies),
            },
            requires_human_review=has_critical,
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
        """
        规则引擎：对比 _ANOMALY_RULES，输出异常列表。

        severity:
          critical — 超出 critical 阈值（>= 立即复核）
          warn     — 超出普通阈值但未到 critical（关注但不阻断）
        """
        anomalies = []
        for field_name, rule in _ANOMALY_RULES.items():
            val = metrics.get(field_name)
            if val is None or not isinstance(val, (int, float)):
                continue
            val = float(val)

            # 判断是否超出 critical 范围
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
