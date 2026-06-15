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

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from rhythmind.agents.coach_agent import CoachAgent
from rhythmind.agents.data_agent import DataAgent
from rhythmind.agents.metrics_agent import MetricsProcessor
from rhythmind.core.hermes_base import AgentContext, HermesRunResult

logger = logging.getLogger(__name__)


# ── SSE 事件类型 ──────────────────────────────────────────────────────────────

def _sse_event(event: str, data: Any) -> dict[str, str]:
    """构造 SSE 消息字典（供 sse_starlette 使用）。"""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


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

    async def run_stream(
        self,
        user_id: str,
        session_id: str,
        input_data: dict[str, Any],
        metrics_agent: MetricsProcessor | None = None,
        data_agent: DataAgent | None = None,
        coach_agent: CoachAgent | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """
        流式 SSE 版本：每个 Agent 完成后立即推送进度事件。

        SSE 事件序列：
          start         → 工作流开始
          metrics_done  → MetricsAgent 完成（含异常摘要和负荷级别）
          data_done     → DataAgent 完成（含数据解读摘要）
          coach_done    → CoachAgent 完成（含训练计划）
          error         → 任意步骤出错
          done          → 全部完成

        Args:
            user_id, session_id, input_data: 同 run()
            metrics_agent, data_agent, coach_agent: 可注入池化实例（可选）
        """
        # ── start ────────────────────────────────────────────────────────
        yield _sse_event("start", {
            "session_id": session_id,
            "user_id": user_id,
            "message": "开始分析健康数据...",
        })

        # ── Step 1: MetricsAgent ──────────────────────────────────────────
        _metrics = metrics_agent or MetricsProcessor(user_id=user_id)
        metrics_ctx = AgentContext(
            user_id=user_id, session_id=session_id,
            task_type="analyze_metrics", input_data=input_data,
        )
        try:
            metrics_result = await _metrics.run(metrics_ctx)
        except Exception as e:
            yield _sse_event("error", {"step": "metrics", "message": str(e)})
            return

        ma = metrics_result.output or {}
        yield _sse_event("metrics_done", {
            "load_level": ma.get("load_level", "unknown"),
            "anomaly_count": len(ma.get("anomalies", [])),
            "influx_available": ma.get("influx_available", False),
            "latency_ms": round(metrics_result.latency_ms, 1),
            "message": "指标分析完成",
        })

        # ── Step 2: DataAgent ─────────────────────────────────────────────
        data_input = {**input_data, "metrics_analysis": ma}
        _data = data_agent or DataAgent(user_id=user_id)
        data_ctx = AgentContext(
            user_id=user_id, session_id=session_id,
            task_type="upload_data", input_data=data_input,
        )
        try:
            data_result = await _data.run(data_ctx)
        except Exception as e:
            yield _sse_event("error", {"step": "data", "message": str(e)})
            return

        if not data_result.success:
            yield _sse_event("error", {"step": "data", "message": "数据解读合规检查未通过"})
            return

        dr = data_result.output or {}
        yield _sse_event("data_done", {
            "summary": dr.get("summary", ""),
            "concerns_count": len(dr.get("concerns", [])),
            "latency_ms": round(data_result.latency_ms, 1),
            "message": "数据解读完成",
        })

        # ── Step 3: CoachAgent ────────────────────────────────────────────
        coach_input = {
            **input_data,
            "data_report": dr,
            "metrics_analysis": ma,
        }
        _coach = coach_agent or CoachAgent(user_id=user_id)
        coach_ctx = AgentContext(
            user_id=user_id, session_id=session_id,
            task_type="generate_plan", input_data=coach_input,
        )
        try:
            coach_result = await _coach.run(coach_ctx)
        except Exception as e:
            yield _sse_event("error", {"step": "coach", "message": str(e)})
            return

        cp = coach_result.output or {}
        yield _sse_event("coach_done", {
            "plan_name": (cp.get("today_plan") or {}).get("name", ""),
            "motivation": cp.get("motivation", ""),
            "latency_ms": round(coach_result.latency_ms, 1),
            "message": "训练计划生成完成",
        })

        # ── done：完整结果 ────────────────────────────────────────────────
        swarm = SwarmResult(
            metrics_result=metrics_result,
            data_result=data_result,
            coach_result=coach_result,
            success=data_result.success and coach_result.success,
            user_id=user_id,
            session_id=session_id,
        )
        yield _sse_event("done", swarm.final_output)

    async def run(
        self,
        user_id: str,
        session_id: str,
        input_data: dict[str, Any],
        metrics_agent: MetricsProcessor | None = None,
        data_agent: DataAgent | None = None,
        coach_agent: CoachAgent | None = None,
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
        _metrics = metrics_agent or MetricsProcessor(user_id=user_id)
        metrics_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="analyze_metrics",
            input_data=input_data,
        )
        metrics_result = await _metrics.run(metrics_ctx)
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
        _data = data_agent or DataAgent(user_id=user_id)
        data_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="upload_data",
            input_data=data_input,
        )
        data_result = await _data.run(data_ctx)

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
        _coach = coach_agent or CoachAgent(user_id=user_id)
        coach_ctx = AgentContext(
            user_id=user_id,
            session_id=session_id,
            task_type="generate_plan",
            input_data=coach_input,
        )
        coach_result = await _coach.run(coach_ctx)

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


# ── AG2 Phase 2：真实 AutoGen Swarm 集成 ─────────────────────────────────────

async def run_ag2_swarm(
    user_id: str,
    session_id: str,
    input_data: dict[str, Any],
) -> SwarmResult:
    """
    Phase 2：基于 autogen_agentchat 0.4 Swarm 的真实多 Agent 集成。

    架构：
      HermesBase.run() 包装为 AG2 FunctionTool → 注册到 AssistantAgent
      → Swarm 团队驱动 handoff 消息链

    handoff 约定：
      metrics_agent → data_agent:
        消息携带 MetricsAnalysis JSON，data_agent 解析后调用 HermesBase
      data_agent → coach_agent:
        消息携带 DataReport JSON，coach_agent 生成训练计划

    降级策略：
      autogen 未安装 / 运行时异常 → 自动降级到手动链 SwarmDataCoach.run()
    """
    try:
        import json as _json

        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.base import TaskResult
        from autogen_agentchat.conditions import (
            MaxMessageTermination,
            TextMentionTermination,
        )
        from autogen_agentchat.teams import Swarm
        from autogen_core.tools import FunctionTool
        from autogen_ext.models.openai import OpenAIChatCompletionClient

        from rhythmind.config import settings

        # ── 1. LiteLLM-compat 模型客户端（路由到本地 LiteLLM proxy）─────────
        model_client = OpenAIChatCompletionClient(
            model=settings.model_primary,
            base_url=settings.litellm_url + "/v1",
            api_key=settings.litellm_master_key,
        )

        # ── 2. 将 HermesBase.run() 包装为 AG2 FunctionTool ───────────────────

        # MetricsAgent 工具：接收原始 input_data，返回 MetricsAnalysis JSON
        _metrics_hermes = MetricsProcessor(user_id=user_id)
        async def run_metrics_agent(input_json: str) -> str:
            """运行 MetricsAgent，返回 MetricsAnalysis JSON 字符串。"""
            data = _json.loads(input_json)
            ctx = AgentContext(
                user_id=user_id, session_id=session_id,
                task_type="analyze_metrics", input_data=data,
            )
            result = await _metrics_hermes.run(ctx)
            return _json.dumps(result.output or {}, ensure_ascii=False)

        # DataAgent 工具：接收 metrics_analysis JSON，返回 DataReport JSON
        _data_hermes = DataAgent(user_id=user_id)
        async def run_data_agent(metrics_analysis_json: str) -> str:
            """运行 DataAgent，解读 MetricsAnalysis，返回 DataReport JSON 字符串。"""
            analysis = _json.loads(metrics_analysis_json)
            data = {**input_data, "metrics_analysis": analysis}
            ctx = AgentContext(
                user_id=user_id, session_id=session_id,
                task_type="upload_data", input_data=data,
            )
            result = await _data_hermes.run(ctx)
            if not result.success:
                return _json.dumps({"error": "compliance_blocked"}, ensure_ascii=False)
            return _json.dumps(result.output or {}, ensure_ascii=False)

        # CoachAgent 工具：接收 data_report JSON，返回训练计划 JSON
        _coach_hermes = CoachAgent(user_id=user_id)
        async def run_coach_agent(data_report_json: str) -> str:
            """运行 CoachAgent，生成训练计划，返回 Plan JSON 字符串。"""
            report = _json.loads(data_report_json)
            data = {**input_data, "data_report": report}
            ctx = AgentContext(
                user_id=user_id, session_id=session_id,
                task_type="generate_plan", input_data=data,
            )
            result = await _coach_hermes.run(ctx)
            return _json.dumps(result.output or {}, ensure_ascii=False)

        metrics_tool = FunctionTool(run_metrics_agent, description="运行指标分析 Agent，输入原始健康数据 JSON")
        data_tool    = FunctionTool(run_data_agent,    description="运行数据解读 Agent，输入 MetricsAnalysis JSON")
        coach_tool   = FunctionTool(run_coach_agent,   description="运行教练 Agent，输入 DataReport JSON，生成训练计划")

        # ── 3. 创建 AG2 AssistantAgent（三个角色）──────────────────────────
        metrics_ag2 = AssistantAgent(
            name="metrics_agent",
            model_client=model_client,
            tools=[metrics_tool],
            handoffs=["data_agent"],
            system_message=(
                "你是 MetricsAgent，负责分析健康指标数据。"
                "调用 run_metrics_agent 工具处理用户数据，"
                "然后将结果 handoff 给 data_agent。"
            ),
        )
        data_ag2 = AssistantAgent(
            name="data_agent",
            model_client=model_client,
            tools=[data_tool],
            handoffs=["coach_agent"],
            system_message=(
                "你是 DataAgent，负责深度解读健康数据。"
                "调用 run_data_agent 工具处理 MetricsAnalysis，"
                "然后将结果 handoff 给 coach_agent。"
            ),
        )
        coach_ag2 = AssistantAgent(
            name="coach_agent",
            model_client=model_client,
            tools=[coach_tool],
            handoffs=[],
            system_message=(
                "你是 CoachAgent，负责制定训练计划。"
                "调用 run_coach_agent 工具生成计划，"
                "完成后输出 'ANALYSIS_COMPLETE' 结束会话。"
            ),
        )

        # ── 4. 组建 Swarm 团队 ────────────────────────────────────────────
        termination = (
            TextMentionTermination("ANALYSIS_COMPLETE")
            | MaxMessageTermination(max_messages=12)
        )
        team = Swarm(
            participants=[metrics_ag2, data_ag2, coach_ag2],
            termination_condition=termination,
        )

        # ── 5. 启动 Swarm，注入初始任务消息 ──────────────────────────────
        initial_msg = (
            f"请分析以下健康数据并生成训练计划：\n"
            f"{_json.dumps(input_data, ensure_ascii=False)}"
        )
        task_result: TaskResult = await team.run(task=initial_msg)

        logger.info(
            "ag2_swarm done messages=%d stop=%s",
            len(task_result.messages),
            task_result.stop_reason,
        )

        # ── 6. 从 AG2 消息历史提取三级结果，封装为 SwarmResult ───────────
        # AG2 模式下我们从 HermesBase 实例直接拿最后一次 run() 结果
        # （工具函数闭包持有 HermesBase 实例）
        from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult

        def _make_result(hermes_agent, output_json: str, agent_name: str) -> HermesRunResult:
            try:
                output = _json.loads(output_json)
            except Exception:
                output = {}
            return HermesRunResult(
                compliance=ComplianceResult(
                    level=ComplianceLevel.PASS,
                    output=output,
                    confidence=0.9,
                ),
                agent=agent_name,
                user_id=user_id,
                task_type=agent_name,
                latency_ms=0.0,
            )

        # 提取各工具最后一次输出（从消息历史中最后一条 tool_call result）
        tool_outputs: dict[str, str] = {}
        for msg in task_result.messages:
            if hasattr(msg, "content") and hasattr(msg, "source"):
                src = getattr(msg, "source", "")
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.startswith("{"):
                    tool_outputs[src] = content

        metrics_out = tool_outputs.get("metrics_agent", "{}")
        data_out    = tool_outputs.get("data_agent", "{}")
        coach_out   = tool_outputs.get("coach_agent", "{}")

        return SwarmResult(
            metrics_result=_make_result(_metrics_hermes, metrics_out, "metrics_agent"),
            data_result=_make_result(_data_hermes, data_out, "data_agent"),
            coach_result=_make_result(_coach_hermes, coach_out, "coach_agent"),
            success=True,
            user_id=user_id,
            session_id=session_id,
        )

    except ImportError as e:
        logger.warning("ag2_swarm import_error=%s fallback=SwarmDataCoach", e)
        return await SwarmDataCoach().run(user_id, session_id, input_data)
    except Exception as e:
        logger.error("ag2_swarm runtime_error=%s fallback=SwarmDataCoach", e)
        return await SwarmDataCoach().run(user_id, session_id, input_data)


def _empty_run_result(user_id: str, session_id: str, agent: str) -> HermesRunResult:
    """构造一个空的失败结果（避免 None 值）。"""
    from rhythmind.core.compliance.gate import ComplianceLevel, ComplianceResult
    return HermesRunResult(
        compliance=ComplianceResult(
            level=ComplianceLevel.BLOCK,
            output=None,
            confidence=0.0,
            compliance_block=True,
        ),
        agent=agent,
        user_id=user_id,
        task_type="skipped",
        latency_ms=0.0,
    )
