# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
agents/coach_agent.py — AI Sport 教练 Agent（模块 M2）

在 AG2 Swarm 中接收 DataAgent 的解读结果，
生成个性化训练计划和当日训练指导。

上游（DataAgent）→ CoachAgent 的传递约定：
  input_data["data_report"] = DataAgent 的 output dict
  input_data["sport_type"]  = 运动类型
  input_data["user_goal"]   = 用户目标（减脂/增肌/马拉松/...）

输出格式：
  {
    "today_plan": {...},     # 当日训练计划
    "weekly_load": str,      # 周训练量建议
    "recovery_advice": str,  # 恢复建议
    "motivation": str        # 激励话语
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

# 运动目标 → 教练侧重方向映射
GOAL_FOCUS_MAP = {
    "减脂": "有氧优先，控制强度在 Z2-Z3，配合饮食",
    "增肌": "力量训练为主，确保蛋白质摄入，充足恢复",
    "马拉松": "长跑耐力，渐进增量，心率控制在 Z2",
    "体能": "混合训练，兼顾力量和有氧",
    "健康维护": "低强度持续，养成习惯优先",
}


class CoachAgent(HermesBase):
    """
    运动教练 Agent。

    Swarm 中由 DataAgent 触发，读取数据解读报告后生成训练计划。
    """

    def __init__(self, user_id: str) -> None:
        super().__init__("coach_agent", user_id)

    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
    ) -> AgentResult:
        bound_log = log.bind(agent="coach_agent", user=ctx.user_id)

        # ── 读取上游 DataAgent 报告 ────────────────────────────────────────
        data_report: dict[str, Any] = ctx.input_data.get("data_report", {})
        sport_type: str = ctx.input_data.get("sport_type", "general")
        user_goal: str = ctx.input_data.get("user_goal", "健康维护")

        # ── 从记忆中取训练历史 ────────────────────────────────────────────
        training_history: dict = memory_ctx.get("training_history", {}) or {}
        current_plan: dict = memory_ctx.get("current_plan", {}) or {}
        weekly_volume_km: float = float(training_history.get("weekly_volume_km", 0))

        goal_focus = GOAL_FOCUS_MAP.get(user_goal, GOAL_FOCUS_MAP["健康维护"])

        # ── 构建 Prompt ───────────────────────────────────────────────────
        prompt = self._build_prompt(
            data_report=data_report,
            sport_type=sport_type,
            user_goal=user_goal,
            goal_focus=goal_focus,
            current_plan=current_plan,
            weekly_volume_km=weekly_volume_km,
        )

        # raw_json 必须提前初始化为 ""：若 call_llm() 抛异常（超时/网络/JSON 解析），
        # except 块引用 raw_json 时不会触发 NameError 二次冒泡。
        raw_json = ""
        try:
            raw_json = await self.call_llm(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是律动 AI 平台的专业运动教练，"
                            "持有 ACSM 认证，擅长个性化训练计划制定。"
                            "回复简洁、专业、有激励性，避免医疗建议。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.4,
                # gemma-4-e4b 4bit 实际产出 ~350 tokens；600 留余量并把响应压到 60s 内
                max_tokens=600,
            )
            plan = json.loads(raw_json)
        except ComplianceBlockedError:
            raise  # 前置审查 BLOCK → 交由 HermesBase.run() 统一处理
        except Exception as e:
            bound_log.error("coach_agent llm_error=%s", e)
            plan = self._fallback_plan(sport_type, user_goal)

        # 训练量渐进安全检查（>10% 周增量 → WARN）
        new_volume = float(plan.get("today_plan", {}).get("distance_km", 0))
        confidence = 0.90
        if weekly_volume_km > 0 and new_volume > weekly_volume_km * 0.15:
            bound_log.warning(
                "coach_agent load_spike new=%.1f base=%.1f", new_volume, weekly_volume_km
            )
            confidence = 0.65  # 触发 ComplianceGate WARN

        return AgentResult(
            output=plan,
            confidence=confidence,
            skill_candidates=[
                f"training_plan_{sport_type}_{user_goal}",
                f"load_progression_{sport_type}",
            ],
            memory_updates={
                "current_plan": plan,
                "training_history": {
                    **training_history,
                    "weekly_volume_km": weekly_volume_km + new_volume,
                    "last_sport_type": sport_type,
                    "user_goal": user_goal,
                },
            },
        )

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_prompt(
        data_report: dict,
        sport_type: str,
        user_goal: str,
        goal_focus: str,
        current_plan: dict,
        weekly_volume_km: float,
    ) -> str:
        return f"""
基于以下数据解读报告，为用户制定今日训练计划：

**数据解读摘要**: {data_report.get('summary', '无')}
**主要关注点**: {', '.join(data_report.get('concerns', [])) or '无'}
**运动类型**: {sport_type}
**用户目标**: {user_goal}（{goal_focus}）
**本周已累计**: {weekly_volume_km:.1f} km
**当前计划**: {json.dumps(current_plan, ensure_ascii=False) if current_plan else '无'}

请返回以下 JSON（中文）：
{{
  "today_plan": {{
    "name": "计划名称",
    "duration_min": 训练时长分钟数,
    "distance_km": 目标距离（如适用，否则0）,
    "intensity": "低/中/高",
    "hr_target_zone": "Z1-Z5中的目标区间",
    "exercises": ["动作1描述", "动作2描述"],
    "warm_up": "热身方案",
    "cool_down": "放松方案"
  }},
  "weekly_load": "本周训练量建议（一句话）",
  "recovery_advice": "恢复建议（睡眠/营养/拉伸）",
  "motivation": "今日激励话语（一句话，积极正向）"
}}
禁止出现医疗诊断或处方内容。
"""

    @staticmethod
    def _fallback_plan(sport_type: str, user_goal: str) -> dict:
        return {
            "today_plan": {
                "name": f"{sport_type} 基础训练",
                "duration_min": 30,
                "distance_km": 0,
                "intensity": "低",
                "hr_target_zone": "Z2",
                "exercises": ["有氧慢跑 20 分钟", "全身拉伸 10 分钟"],
                "warm_up": "动态拉伸 5 分钟",
                "cool_down": "静态拉伸 5 分钟",
            },
            "weekly_load": "本周建议保持现有训练量，循序渐进。",
            "recovery_advice": "保证 7-8 小时睡眠，补充优质蛋白质。",
            "motivation": "每一步都是进步，坚持就是胜利！",
        }
