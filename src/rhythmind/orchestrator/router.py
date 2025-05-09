# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
orchestrator/router.py — HealthRouter：AG2 编排入口

职责：
  1. 意图分类（intent classification）
  2. 路由到对应工作流（Swarm/Graph/Direct）
  3. 前置合规检查（ComplianceGate.pre_check）
  4. LoopGuard 节流
  5. 统一错误处理和 WorkflowResult 封装

意图分类策略（Phase 1）：
  规则匹配 → fast 模型 fallback（避免额外延迟）
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
import sys
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass
from typing import Any

from rhythmind.config import settings
from rhythmind.core.compliance import ComplianceGate
from rhythmind.orchestrator.loop_guard import LoopGuard
from rhythmind.orchestrator.workflows.swarm_data_coach import SwarmDataCoach, SwarmResult

logger = logging.getLogger(__name__)


class WorkflowStatus(StrEnum):
    SUCCESS = "success"
    BLOCKED = "blocked"         # ComplianceGate 拦截
    THROTTLED = "throttled"     # LoopGuard 节流
    ERROR = "error"             # 未预期异常


@dataclass
class WorkflowResult:
    status: WorkflowStatus
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    session_id: str = ""
    user_id: str = ""

    @classmethod
    def blocked(cls, reason: str, user_id: str = "") -> "WorkflowResult":
        return cls(
            status=WorkflowStatus.BLOCKED,
            message=f"合规检查不通过：{reason}",
            user_id=user_id,
        )

    @classmethod
    def throttled(cls, user_id: str = "") -> "WorkflowResult":
        return cls(
            status=WorkflowStatus.THROTTLED,
            message="操作过于频繁，请稍后再试。",
            user_id=user_id,
        )

    @classmethod
    def error(cls, msg: str, user_id: str = "") -> "WorkflowResult":
        return cls(
            status=WorkflowStatus.ERROR,
            message=msg,
            user_id=user_id,
        )


# 意图 → 工作流 ID 映射
INTENT_MAP: dict[str, str] = {
    # 数据上传链（DataAgent → CoachAgent）
    "upload_data":    "swarm_data_coach",
    "sync_wearable":  "swarm_data_coach",
    # 目标设定（CoachAgent only）
    "set_goal":       "swarm_goal_plan",
    # 疼痛/损伤（多 Agent Graph）
    "pain_report":    "graph_rehab_multi",
    # 生理预警（广播 Graph）
    "vitals_alert":   "graph_alert_broadcast",
    # 饮食咨询（DietAgent）
    "diet_query":     "swarm_diet_simple",
    # 社区（Community Agent）
    "community_post": "direct_community",
    # 默认
    "__default__":    "swarm_data_coach",
}

# 意图关键词规则（快速路径，避免 LLM 调用）
INTENT_RULES: list[tuple[list[str], str]] = [
    (["上传", "同步", "garmin", "apple", "华为", "小米", "手环", "手表"], "upload_data"),
    (["目标", "计划", "跑步", "减脂", "增肌", "马拉松"], "set_goal"),
    (["疼", "痛", "受伤", "扭伤", "拉伤", "损伤"], "pain_report"),
    (["心率", "异常", "心跳", "血压", "预警", "alert"], "vitals_alert"),
    (["吃", "饮食", "食谱", "营养", "卡路里", "热量"], "diet_query"),
    (["发帖", "动态", "分享", "打卡"], "community_post"),
]


class HealthRouter:
    """
    路由器主类（单例，在 FastAPI lifespan 中初始化）。
    """

    def __init__(self) -> None:
        self.compliance = ComplianceGate()
        self.loop_guard = LoopGuard()
        self._swarm_data_coach = SwarmDataCoach()

    async def route(
        self,
        user_id: str,
        raw_input: dict[str, Any],
        session_id: str | None = None,
    ) -> WorkflowResult:
        """
        主路由入口。

        Args:
            user_id:    请求用户 ID
            raw_input:  用户原始输入（含 text、数据字段等）
            session_id: 会话 ID（可选，自动生成）
        """
        sid = session_id or str(uuid.uuid4())
        log_ctx = logger.getChild(f"user={user_id} sid={sid}")

        # ── 前置合规检查 ──────────────────────────────────────────────────
        if not self.compliance.pre_check(raw_input):
            log_ctx.warning("router.pre_check BLOCKED")
            return WorkflowResult.blocked("输入包含不允许的内容", user_id=user_id)

        # ── 意图分类 ──────────────────────────────────────────────────────
        intent = self._classify_intent(raw_input)
        workflow_id = INTENT_MAP.get(intent, INTENT_MAP["__default__"])
        log_ctx.info("router.intent=%s workflow=%s", intent, workflow_id)

        # ── LoopGuard 节流 ────────────────────────────────────────────────
        if await self.loop_guard.is_cooling_down(user_id, intent):
            log_ctx.warning("router.loop_guard THROTTLED intent=%s", intent)
            return WorkflowResult.throttled(user_id=user_id)

        # ── 路由执行 ──────────────────────────────────────────────────────
        try:
            return await self._execute_workflow(
                workflow_id=workflow_id,
                user_id=user_id,
                session_id=sid,
                raw_input=raw_input,
                intent=intent,
            )
        except Exception as e:
            log_ctx.exception("router.execute_error workflow=%s", workflow_id)
            return WorkflowResult.error(str(e), user_id=user_id)

    async def _execute_workflow(
        self,
        workflow_id: str,
        user_id: str,
        session_id: str,
        raw_input: dict[str, Any],
        intent: str,
    ) -> WorkflowResult:
        """分发到具体工作流。"""

        if workflow_id == "swarm_data_coach":
            result: SwarmResult = await self._swarm_data_coach.run(
                user_id=user_id,
                session_id=session_id,
                input_data=raw_input,
            )
            if not result.success:
                return WorkflowResult.blocked(
                    "数据解读合规检查未通过", user_id=user_id
                )
            return WorkflowResult(
                status=WorkflowStatus.SUCCESS,
                data=result.final_output,
                session_id=session_id,
                user_id=user_id,
            )

        # Phase 2 工作流（预留占位）
        elif workflow_id in ("graph_rehab_multi", "graph_alert_broadcast"):
            return WorkflowResult(
                status=WorkflowStatus.SUCCESS,
                data={"message": f"工作流 {workflow_id} 将在 Phase 2 实现"},
                session_id=session_id,
                user_id=user_id,
            )

        else:
            return WorkflowResult(
                status=WorkflowStatus.ERROR,
                message=f"未知工作流: {workflow_id}",
                user_id=user_id,
            )

    @staticmethod
    def _classify_intent(raw_input: dict[str, Any]) -> str:
        """
        规则优先意图分类。

        先做关键词匹配（O(n)，< 1ms）；
        匹配不到时 fallback 为 "upload_data"（Phase 2 接 fast 模型）。
        """
        text = " ".join(
            str(v) for v in raw_input.values() if isinstance(v, str)
        ).lower()

        for keywords, intent in INTENT_RULES:
            if any(kw in text for kw in keywords):
                return intent

        # 有结构化数据字段 → 数据上传
        data_fields = {"heart_rate_avg", "steps", "sleep_hours", "hrv", "calories"}
        if data_fields & set(raw_input.keys()):
            return "upload_data"

        return "__default__"

    async def close(self) -> None:
        """应用关闭时释放资源。"""
        await self.loop_guard.close()
