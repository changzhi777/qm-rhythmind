# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
orchestrator/workflows/swarm_data_coach.py — 数据上传 Swarm 工作流（三级链）

流程：MetricsAgent → DataAgent → CoachAgent

AutoGen 0.4 Swarm 核心概念：
  - 每个 Agent 是 AssistantAgent，通过 handoff_to 声明下一个 Agent
  - 由 initiate_swarm_chat() 驱动，消息自动在 Agent 间传递
  - 我们将 HermesBase 包装成 AG2 的 AssistantAgent 工具调用形式

集成策略（Hermes + AG2 Swarm）：
  HermesBase.run() 是完整的异步闭环，将每个 Agent 包装为
  AG2 ConversableAgent 的 "执行函数"，通过 register_for_execution()
  接入 Swarm 消息总线，而非直接继承 AG2 Agent 类。

  好处：
    1. HermesBase 保持独立可测，不依赖 AG2 运行时
    2. AG2 负责消息传递和终止条件
    3. 未来切换 AG2 版本只需修改本文件

三级链 handoff 约定：
  MetricsAgent → DataAgent:
    ctx.input_data["metrics_analysis"] = MetricsAgent.output (MetricsAnalysis)
  DataAgent → CoachAgent:
    ctx.input_data["data_report"]       = DataAgent.output (DataReport)
    ctx.input_data["metrics_analysis"]  = 透传，供 CoachAgent 参考负荷信息
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rhythmind.agents.coach_agent import CoachAgent
from rhythmind.agents.data_agent import DataAgent
from rhythmind.agents.metrics_agent import MetricsAgent
from rhythmind.core.hermes_base import AgentContext, HermesRunResult

logger = logging.getLogger(__name__)


@dataclass
class SwarmResult:
    """Swarm 工作流最终输出（三级）。"""
    metrics_result: HermesRunResult
    data_result: HermesRunResult
    coach_result: HermesRunResult
    success: bool
    user_id: str
    session_id: str

    @property
    def final_output(self) -> dict[str, Any]:
        ma = self.metrics_result.output or {}
        return {
            # 三级输出
            "metrics_analysis": ma,
            "data_report": self.data_result.output,
            "training_plan": self.coach_result.output,
            # 置信度链
            "confidence": {
                "metrics": self.metrics_result.compliance.confidence,
                "data":    self.data_result.compliance.confidence,
                "coach":   self.coach_result.compliance.confidence,
            },
            # 异常摘要（从 MetricsAgent 提取，供前端展示）
            "anomaly_count": len(ma.get("anomalies", [])),
            "load_level": ma.get("load_level", "unknown"),
            "influx_available": ma.get("influx_available", False),
            # 延迟
            "latency_ms": {
                "metrics_agent": round(self.metrics_result.latency_ms, 1),
                "data_agent":    round(self.data_result.latency_ms, 1),
                "coach_agent":   round(self.coach_result.latency_ms, 1),
                "total": round(
                    self.metrics_result.latency_ms
                    + self.data_result.latency_ms
                    + self.coach_result.latency_ms,
                    1,
                ),
            },
        }


class SwarmDataCoach:
    """
    MetricsAgent → DataAgent → CoachAgent 三级 Swarm 工作流。

    直接编排三个 Hermes Agent 的 run() 调用（Phase 1 手动链）。

    终止策略：
      - MetricsAgent 永不 BLOCK（纯规则，降级而非拒绝）
      - DataAgent BLOCK → 停止，不调 CoachAgent
      - CoachAgent BLOCK → 返回完整结果，success=False

    Phase 2 迁移计划：
      引入 autogen_agentchat.teams.Swarm，将 HermesBase 包装为
      AG2 FunctionTool，由 Swarm 驱动消息传递。
    """

    async def run(
        self,
        user_id: str,
        session_id: str,
        input_data: dict[str, Any],
    ) -> SwarmResult:
        """
        执行 MetricsAgent → DataAgent → CoachAgent 链。

        Args:
            user_id:    当前用户 ID
            session_id: 会话 ID（trace 用）
            input_data: 原始用户上传数据（含 sport_type, metrics 等）
        """
        logger.info(
            "swarm.data_coach start user=%s session=%s", user_id, session_id
        )

        # ── Step 1: MetricsAgent（InfluxDB 写入 + 趋势 + 规则）────────────
        metrics_agent = MetricsAgent(user_id=user_id)
        metrics_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="analyze_metrics",
            input_data=input_data,
        )
        metrics_result = await metrics_agent.run(metrics_ctx)
        # MetricsAgent 置信度=1.0，基本不会被 BLOCK；
        # 即使被 BLOCK（极端情况），也继续下游以保障用户体验
        logger.debug(
            "swarm.metrics done influx_ok=%s anomalies=%s load=%s",
            (metrics_result.output or {}).get("write_ok"),
            len((metrics_result.output or {}).get("anomalies", [])),
            (metrics_result.output or {}).get("load_level"),
        )

        # ── Step 2: DataAgent（LLM 深度解读，接收 MetricsAnalysis）─────
        data_input = {
            **input_data,
            "metrics_analysis": metrics_result.output or {},  # 核心 handoff
        }
        data_agent = DataAgent(user_id=user_id)
        data_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="upload_data",
            input_data=data_input,
        )
        data_result = await data_agent.run(data_ctx)

        if not data_result.success:
            logger.warning(
                "swarm.data_coach BLOCKED at DataAgent user=%s", user_id
            )
            return SwarmResult(
                metrics_result=metrics_result,
                data_result=data_result,
                coach_result=_empty_run_result(user_id, session_id, "coach_agent"),
                success=False,
                user_id=user_id,
                session_id=session_id,
            )

        # ── Step 3: CoachAgent（训练计划，接收 DataReport + MetricsAnalysis）
        coach_input = {
            **input_data,
            "data_report":       data_result.output,          # 解读报告
            "metrics_analysis":  metrics_result.output or {},  # 透传负荷信息
        }
        coach_agent = CoachAgent(user_id=user_id)
        coach_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="generate_plan",
            input_data=coach_input,
        )
        coach_result = await coach_agent.run(coach_ctx)

        overall_success = data_result.success and coach_result.success
        logger.info(
            "swarm.data_coach done user=%s success=%s total_ms=%.1f",
            user_id,
            overall_success,
            metrics_result.latency_ms + data_result.latency_ms + coach_result.latency_ms,
        )

        return SwarmResult(
            metrics_result=metrics_result,
            data_result=data_result,
            coach_result=coach_result,
            success=overall_success,
            user_id=user_id,
            session_id=session_id,
        )


# ── AG2 Swarm 增强版（Phase 2 预留）────────────────────────────────────────

async def run_ag2_swarm(
    user_id: str,
    session_id: str,
    input_data: dict[str, Any],
) -> SwarmResult:
    """
    Phase 2：基于 autogen_agentchat.teams.Swarm 的完整实现。

    目前 import guard，避免 autogen 未安装时报错。
    Phase 2 解除注释并删除 SwarmDataCoach 的手动编排。
    """
    try:
        from autogen_agentchat.agents import AssistantAgent  # noqa: F401
        from autogen_agentchat.teams import Swarm  # noqa: F401
        from autogen_agentchat.conditions import MaxMessageTermination  # noqa: F401
        from autogen_ext.models.openai import OpenAIChatCompletionClient  # noqa: F401
        from rhythmind.config import settings  # noqa: F401

        # 将 HermesBase 的输出注册为工具（待 Phase 2 实现）
        # metrics_tool = FunctionTool(MetricsAgent(user_id).run, ...)
        # data_tool    = FunctionTool(DataAgent(user_id).run, ...)
        # coach_tool   = FunctionTool(CoachAgent(user_id).run, ...)
        raise NotImplementedError("Phase 2 AG2 Swarm integration not yet implemented")

    except ImportError as e:
        logger.error("ag2_swarm import_error=%s fallback=SwarmDataCoach", e)
        return await SwarmDataCoach().run(user_id, session_id, input_data)


def _empty_run_result(user_id: str, session_id: str, agent: str) -> HermesRunResult:
    """构造一个空的失败结果（避免 None 值）。"""
    from rhythmind.core.compliance.gate import ComplianceResult, ComplianceLevel
    return HermesRunResult(
        compliance=ComplianceResult(
            level=ComplianceLevel.BLOCK,
            output=None,
            confidence=0.0,
            requires_human_review=True,
        ),
        agent=agent,
        user_id=user_id,
        task_type="skipped",
        latency_ms=0.0,
    )
