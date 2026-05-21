"""
ingestion/engine.py — 数据入库 + AI 分析引擎

职责：
  1. 调用适配器读取数据
  2. 通过 FactManager 写入 HealthFact 知识图谱
  3. 通过 AdapterRouter 调用本地模型生成 AI 分析报告
  4. 存储报告到数据库，支持历史对比
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from rhythmind.adapters.adapter_router import adapter_router
from rhythmind.core.memory.fact_manager import FactManager
from rhythmind.ingestion.base import (
    BaseDataSourceAdapter,
    IngestionResult,
)

logger = logging.getLogger(__name__)


class IngestionEngine:
    """
    数据入库 + AI 分析引擎。

    与数据源完全解耦，只依赖 BaseDataSourceAdapter 接口。
    """

    def __init__(
        self,
        adapter: BaseDataSourceAdapter,
        user_id: str = "garmin_user_001",
        model_spec: str | None = None,
    ) -> None:
        self._adapter = adapter
        self._user_id = user_id
        self._fm = FactManager(user_id)
        self._model_spec = model_spec or "omlX://gemma-4-e4b-it-4bit"

    # ── 数据入库 ─────────────────────────────────────────────────────────

    async def ingest(self) -> IngestionResult:
        """执行完整数据入库流程。"""
        result = IngestionResult()

        errors = self._adapter.validate()
        if errors:
            result.errors = errors
            return result

        # 1. 用户画像
        try:
            profile = self._adapter.load_profile()
            await self._fm.write_fact("profile", "gender", profile.gender, source=self._adapter.source_name)
            await self._fm.write_fact("profile", "height_cm", profile.height_cm, source=self._adapter.source_name)
            await self._fm.write_fact("profile", "weight_kg", profile.weight_kg, source=self._adapter.source_name)
            await self._fm.write_fact("profile", "bmi", round(profile.bmi, 1), source=self._adapter.source_name)
            await self._fm.write_fact("profile", "age", profile.age, source=self._adapter.source_name)
            if profile.vo2_max:
                await self._fm.write_fact("profile", "vo2_max", profile.vo2_max, source=self._adapter.source_name)
            if profile.resting_hr:
                await self._fm.write_fact("profile", "resting_hr", profile.resting_hr, source=self._adapter.source_name)
            if profile.max_hr:
                await self._fm.write_fact("profile", "max_hr", profile.max_hr, source=self._adapter.source_name)
            if profile.hr_zones:
                await self._fm.write_fact("profile", "hr_zones", profile.hr_zones, source=self._adapter.source_name)
            result.profile_records += 9
        except Exception as e:
            result.errors.append(f"profile: {e}")
            logger.warning("ingest profile error: %s", e)

        # 2. 运动活动
        try:
            activities = self._adapter.load_activities()
            await self._fm.write_fact("activity_summary", "total_count", len(activities), source=self._adapter.source_name)

            # 按年统计
            from collections import defaultdict
            year_stats: dict[int, dict] = defaultdict(lambda: {"count": 0, "distance": 0, "duration": 0})
            for a in activities:
                y = a.date.year
                year_stats[y]["count"] += 1
                year_stats[y]["distance"] += a.distance_meters
                year_stats[y]["duration"] += a.duration_seconds
            await self._fm.write_fact("activity_summary", "yearly", dict(year_stats), source=self._adapter.source_name)

            # 跑步专项
            runs = [a for a in activities if a.activity_type == "running"]
            total_run_km = sum(r.distance_meters for r in runs) / 1000
            avg_pace = sum(r.pace_min_per_km for r in runs if r.pace_min_per_km) / max(1, len([r for r in runs if r.pace_min_per_km]))
            avg_hr = sum(r.avg_hr for r in runs if r.avg_hr) / max(1, len([r for r in runs if r.avg_hr]))
            await self._fm.write_fact("running", "summary", {
                "total_runs": len(runs),
                "total_km": round(total_run_km, 0),
                "avg_pace_min_per_km": round(avg_pace, 1),
                "avg_hr": round(avg_hr, 0),
            }, source=self._adapter.source_name)

            result.activity_records += 3
        except Exception as e:
            result.errors.append(f"activities: {e}")
            logger.warning("ingest activities error: %s", e)

        # 3. 睡眠
        try:
            sleep_records = self._adapter.load_sleep()
            if sleep_records:
                avg_total = sum(s.total_hours for s in sleep_records) / len(sleep_records)
                avg_deep = sum(s.deep_hours for s in sleep_records) / len(sleep_records)
                avg_rem = sum(s.rem_hours for s in sleep_records) / len(sleep_records)
                deep_pct = sum(s.deep_pct for s in sleep_records) / len(sleep_records)
                await self._fm.write_fact("sleep", "summary", {
                    "record_days": len(sleep_records),
                    "avg_total_hours": round(avg_total, 1),
                    "avg_deep_hours": round(avg_deep, 1),
                    "avg_rem_hours": round(avg_rem, 1),
                    "deep_pct": round(deep_pct, 0),
                }, source=self._adapter.source_name)
                result.sleep_records += 1
        except Exception as e:
            result.errors.append(f"sleep: {e}")
            logger.warning("ingest sleep error: %s", e)

        # 4. 身体指标
        try:
            body_metrics = self._adapter.load_body_metrics()
            vo2_values = [m.vo2_max for m in body_metrics if m.vo2_max]
            hrv_values = [m.hrv for m in body_metrics if m.hrv]
            rhr_values = [m.resting_hr for m in body_metrics if m.resting_hr]
            fitness_ages = [m.fitness_age for m in body_metrics if m.fitness_age]

            metrics_data: dict[str, Any] = {"total_records": len(body_metrics)}
            if vo2_values:
                metrics_data["vo2_max_latest"] = vo2_values[-1]
                metrics_data["vo2_max_max"] = max(vo2_values)
            if hrv_values:
                metrics_data["hrv_avg"] = round(sum(hrv_values) / len(hrv_values), 1)
                metrics_data["hrv_max"] = max(hrv_values)
            if rhr_values:
                metrics_data["resting_hr_avg"] = round(sum(rhr_values) / len(rhr_values), 0)
            if fitness_ages:
                metrics_data["fitness_age_latest"] = fitness_ages[-1]

            await self._fm.write_fact("body_metrics", "summary", metrics_data, source=self._adapter.source_name)
            result.body_metric_records += 1
        except Exception as e:
            result.errors.append(f"body_metrics: {e}")
            logger.warning("ingest body_metrics error: %s", e)

        # 5. 训练指标
        try:
            tm = self._adapter.load_training_metrics()
            await self._fm.write_fact("training", "metrics", {
                "endurance_score": tm.endurance_score,
                "endurance_class": tm.endurance_classification,
                "hill_score": tm.hill_score,
                "acute_load": tm.acute_load,
                "chronic_load": tm.chronic_load,
                "acwr": tm.acwr,
                "acwr_status": tm.acwr_status,
                "readiness_score": tm.training_readiness_score,
                "readiness_level": tm.training_readiness_level,
                "race_predictions": tm.race_predictions,
            }, source=self._adapter.source_name)
            result.training_records += 1
        except Exception as e:
            result.errors.append(f"training: {e}")
            logger.warning("ingest training error: %s", e)

        # 6. 健康事件
        try:
            events = self._adapter.load_health_events()
            if events:
                await self._fm.write_fact("health_events", "abnormal_hr", {
                    "total_count": len(events),
                    "threshold": events[0].threshold if events else 0,
                    "recent": [{"date": e.date, "value": e.value} for e in events[-5:]],
                }, source=self._adapter.source_name)
                result.health_event_records += 1
        except Exception as e:
            result.errors.append(f"health_events: {e}")
            logger.warning("ingest health_events error: %s", e)

        logger.info("ingestion complete: %s records, %d errors", result.total, len(result.errors))
        return result

    # ── AI 分析 ──────────────────────────────────────────────────────────

    async def analyze(self) -> str:
        """调用本地模型生成 AI 健康分析报告。"""
        facts = await self._fm.get_all_current()

        if not facts:
            return "无可用数据，请先执行入库。"

        # 构建事实摘要
        fact_summary = []
        for f in facts:
            fact_summary.append(f"- [{f.subject}/{f.predicate}]: {json.dumps(f.object_json, ensure_ascii=False)}")

        system_prompt = """你是一位专业的运动健康 AI 分析师。根据用户的健康数据事实，生成一份专业的中文分析报告。

报告格式要求：
1. **总体评价**（1-2段）
2. **运动能力评估**（VO2Max、耐力、配速分析）
3. **健康风险评估**（心率、HRV、睡眠）
4. **训练负荷分析**（急性/慢性负荷比）
5. **赛事能力预测**（基于当前数据）
6. **个性化建议**（3-5条具体可执行的建议）

注意：
- 所有分析基于事实数据，不做无依据推测
- 如果某项数据异常，指出具体问题和建议
- 语言专业但不晦涩，适合运动爱好者阅读
- 报告长度控制在 800-1200 字"""

        user_prompt = f"""以下是用户的健康数据事实（来自 Garmin Connect 导出）：

{chr(10).join(fact_summary)}

请基于以上数据生成专业健康分析报告。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("calling local model %s for analysis...", self._model_spec)

        # 直接创建长超时适配器（分析报告生成耗时较长）
        if self._model_spec.startswith("omlX://"):
            from rhythmind.adapters.omlX_adapter import OMLXAdapter
            model_name = self._model_spec[len("omlX://"):]
            analysis_adapter = OMLXAdapter(model_name, timeout=120.0)
            report = await analysis_adapter.chat(
                messages, temperature=0.4, max_tokens=4096,
            )
        else:
            report = await adapter_router.chat(
                messages,
                model_spec=self._model_spec,
                temperature=0.4,
                max_tokens=4096,
            )
        logger.info("AI analysis complete, %d chars", len(report))

        # 存储报告到 DB
        await self._fm.write_fact("ai_report", "analysis", {
            "content": report,
            "model": self._model_spec,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }, source="ai_analysis")

        return report

    # ── 查询 ─────────────────────────────────────────────────────────────

    async def get_dashboard_data(self) -> dict[str, Any]:
        """获取仪表盘所需的所有数据。"""
        facts = await self._fm.get_all_current()
        data: dict[str, Any] = {}
        for f in facts:
            key = f"{f.subject}.{f.predicate}"
            data[key] = f.object_json
        return data

    async def get_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取历史 AI 分析报告列表。"""
        history = await self._fm.query_history("ai_report", "analysis", limit=limit)
        reports = []
        for f in history:
            obj = f.object_json
            if isinstance(obj, dict) and "content" in obj:
                reports.append({
                    "id": f.id,
                    "content": obj["content"],
                    "model": obj.get("model", ""),
                    "timestamp": obj.get("timestamp", ""),
                    "is_current": f.is_current,
                })
        return reports
