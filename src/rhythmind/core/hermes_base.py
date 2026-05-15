# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/hermes_base.py — HermesBase：所有 Agent 的抽象基类

六步闭环（Hermes Pattern v2，增加 prompt 合规前置）：
  1. retrieve_memory  — 从 MemoryManager 召回历史上下文
  2. retrieve_skills  — 从 QMD agent_skills 检索相关技能
  3. execute          — 子类实现具体业务逻辑（抽象方法）
     └─ call_llm()   — [新增] 透明 prompt 审查：gemma-4-e4b 本地预检
  4. compliance_check — ComplianceGate 三级输出分级（output 后置检查）
  5. extract_skills + update_memory — 沉淀经验、更新记忆

合规双层防护：
  前置（call_llm 内）— gemma-4-e4b 审查 prompt 意图，拦截危险请求
  后置（Step 4）    — ComplianceGate 关键词扫描 + 置信度分级

设计约束：
  - 全链路 async/await，禁止 sync I/O
  - call_llm() 审查超时或 gemma 不可用 → 降级放行，主流程不中断
  - 审查 BLOCK → raise ComplianceBlockedError（在 execute 内捕获或上抛）
  - 每步均有 structlog 埋点，便于 OpenTelemetry 采集
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from rhythmind.config import settings
from rhythmind.core.compliance import (
    AuditLevel,
    AuditResult,
    ComplianceGate,
    ComplianceLevel,
    ComplianceResult,
    PromptAuditor,
)
from rhythmind.core.memory import MemoryManager, MemoryRecallResult, MemoryType
from rhythmind.core.qmd import QMDClient, QMDUnavailableError
from rhythmind.core.skill import SkillEngine

log = structlog.get_logger(__name__)


# ── 异常 ──────────────────────────────────────────────────────────────────

class ComplianceBlockedError(Exception):
    """
    call_llm() 前置审查判定 BLOCK 时抛出。

    execute() 内可选择捕获并返回降级 AgentResult，
    或让其上浮由 HermesBase.run() 统一处理。
    """
    def __init__(self, reason: str, audit: AuditResult | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.audit = audit


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class AgentContext:
    """Agent 运行上下文，由 HealthRouter 构建后传入。"""
    user_id: str
    session_id: str
    task_type: str
    input_data: dict[str, Any]
    confidence_threshold: float = 0.75
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """execute() 的返回值。"""
    output: Any
    confidence: float
    skill_candidates: list[str] = field(default_factory=list)
    memory_updates: dict[str, Any] = field(default_factory=dict)
    requires_human_review: bool = False


@dataclass
class HermesRunResult:
    """HermesBase.run() 最终返回，包含完整上下文供 Swarm 传递。"""
    compliance: ComplianceResult
    agent: str
    user_id: str
    task_type: str
    latency_ms: float
    # prompt 审查结果（可选，用于追踪和审计）
    audit_result: AuditResult | None = None
    output: Any = field(init=False)
    success: bool = field(init=False)

    def __post_init__(self) -> None:
        self.output = self.compliance.output
        self.success = self.compliance.level != ComplianceLevel.BLOCK


# ── 抽象基类 ──────────────────────────────────────────────────────────────

class HermesBase(ABC):
    """
    所有健康 Agent 的基类。

    子类只需实现 execute()，用 await self.call_llm() 替代直接的 LLM 调用。
    合规双层防护对业务代码完全透明。
    """

    def __init__(self, agent_name: str, user_id: str) -> None:
        self.agent_name = agent_name
        self.user_id = user_id

        self.memory = MemoryManager(user_id=user_id, agent=agent_name)
        self.skill = SkillEngine(agent=agent_name)
        self.qmd = QMDClient()
        self.compliance = ComplianceGate()
        self.auditor = PromptAuditor()   # gemma-4-e4b 本地审查器

        self._log = log.bind(agent=agent_name, user_id=user_id)

    # ── 六步闭环主入口 ────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext) -> HermesRunResult:
        """
        六步闭环主入口。

        Step 3 内部通过 call_llm() 触发前置合规审查（gemma-4-e4b）。
        Step 4 对输出做后置关键词扫描（ComplianceGate）。
        两层独立，互不依赖。
        """
        t0 = time.perf_counter()
        bound_log = self._log.bind(session=ctx.session_id, task=ctx.task_type)
        last_audit: AuditResult | None = None

        # ── Step 1: 召回历史记忆 ──────────────────────────────────────────
        bound_log.debug("hermes.run step=1 recall_memory")
        memory_ctx: MemoryRecallResult = await self.memory.recall(ctx.task_type)

        # ── Step 2: 检索技能库 ────────────────────────────────────────────
        bound_log.debug("hermes.run step=2 retrieve_skills")
        skill_ctx: list[dict[str, Any]] = []
        try:
            skill_ctx = await self.qmd.query(
                collection="agent_skills",
                query=ctx.task_type,
                top_k=settings.qmd_top_k,
            )
        except QMDUnavailableError:
            bound_log.warning("hermes.run qmd_unavailable fallback=empty_skills")

        # ── Step 3: 执行业务逻辑（call_llm 内含前置审查）────────────────
        bound_log.debug("hermes.run step=3 execute")
        try:
            raw_result: AgentResult = await self.execute(ctx, memory_ctx, skill_ctx)
        except ComplianceBlockedError as e:
            # 前置审查 BLOCK：构造拒绝结果
            bound_log.warning("hermes.run prompt_BLOCKED reason=%s", e.reason)
            latency_ms = (time.perf_counter() - t0) * 1000
            blocked_compliance = _make_blocked_compliance(str(e))
            return HermesRunResult(
                compliance=blocked_compliance,
                agent=self.agent_name,
                user_id=self.user_id,
                task_type=ctx.task_type,
                latency_ms=latency_ms,
                audit_result=e.audit,
            )

        if raw_result.requires_human_review:
            bound_log.warning("hermes.run human_review_required by_agent=True")

        # ── Step 4: 后置合规检查（output 关键词扫描）────────────────────
        bound_log.debug("hermes.run step=4 compliance_check")
        checked: ComplianceResult = self.compliance.validate(raw_result)

        if checked.level == ComplianceLevel.BLOCK or raw_result.requires_human_review:
            checked.requires_human_review = True
            bound_log.warning(
                "hermes.run output_BLOCKED kws=%s", checked.triggered_keywords
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            return HermesRunResult(
                compliance=checked,
                agent=self.agent_name,
                user_id=self.user_id,
                task_type=ctx.task_type,
                latency_ms=latency_ms,
                audit_result=last_audit,
            )

        # ── Step 5a: 提取技能 ─────────────────────────────────────────────
        bound_log.debug("hermes.run step=5a extract_skills")
        extracted_skills = await self.skill.extract(
            task_type=ctx.task_type,
            skill_candidates=checked.skill_candidates,
            output=checked.output,
            confidence=checked.confidence,
        )
        if extracted_skills:
            await self.skill.persist_to_qmd(extracted_skills)

        # ── Step 5b: 更新记忆 ─────────────────────────────────────────────
        bound_log.debug("hermes.run step=5b update_memory")
        if checked.memory_updates:
            await self.memory.update(checked.memory_updates)

        latency_ms = (time.perf_counter() - t0) * 1000
        bound_log.info(
            "hermes.run DONE level=%s confidence=%.2f latency_ms=%.1f",
            checked.level, checked.confidence, latency_ms,
        )

        return HermesRunResult(
            compliance=checked,
            agent=self.agent_name,
            user_id=self.user_id,
            task_type=ctx.task_type,
            latency_ms=latency_ms,
            audit_result=last_audit,
        )

    @abstractmethod
    async def execute(
        self,
        ctx: AgentContext,
        memory_ctx: MemoryRecallResult,
        skill_ctx: list[dict[str, Any]],
    ) -> AgentResult:
        """子类实现业务逻辑，用 await self.call_llm() 发起 LLM 请求。"""

    # ── call_llm()：带前置合规审查的 LLM 调用 ────────────────────────────

    async def call_llm(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """
        带 gemma-4-e4b 前置审查的统一 LLM 调用接口。

        流程：
          1. PromptAuditor.audit(messages) → AuditResult
          2. BLOCK  → raise ComplianceBlockedError（不调用主模型）
          3. WARN   → 追加安全约束到 system prompt
          4. PASS   → 直接调用主模型

        Args:
            messages:        OpenAI 格式 messages 列表
            model:           模型别名，默认 settings.model_primary
            temperature:     采样温度
            max_tokens:      最大输出 tokens
            response_format: {"type": "json_object"} 等

        Returns:
            主模型输出的文本内容（str）

        Raises:
            ComplianceBlockedError: 审查判定 BLOCK
        """
        bound_log = self._log

        # ── 前置审查（gemma-4-e4b 本地）──────────────────────────────────
        audit = await self.auditor.audit(messages)
        bound_log.debug(
            "call_llm.audit level=%s score=%.2f available=%s",
            audit.level, audit.overall_score, audit.auditor_available,
        )

        if audit.level == AuditLevel.BLOCK:
            raise ComplianceBlockedError(
                reason=f"prompt 审查拦截：{audit.reason}（score={audit.overall_score:.2f}）",
                audit=audit,
            )

        # WARN：将审查器建议的约束注入 system prompt
        final_messages = list(messages)
        if audit.level == AuditLevel.WARN and audit.extra_constraints:
            constraints_text = "\n".join(
                f"- {c}" for c in audit.extra_constraints
            )
            # 找到 system message 并追加，或在开头插入
            sys_idx = next(
                (i for i, m in enumerate(final_messages) if m.get("role") == "system"),
                None,
            )
            if sys_idx is not None:
                orig = final_messages[sys_idx]["content"]
                final_messages[sys_idx] = {
                    "role": "system",
                    "content": f"{orig}\n\n[安全约束]\n{constraints_text}",
                }
            else:
                final_messages.insert(0, {
                    "role": "system",
                    "content": f"[安全约束]\n{constraints_text}",
                })
            bound_log.info(
                "call_llm.WARN constraints_injected count=%d",
                len(audit.extra_constraints),
            )

        # ── 调用主模型（通过 AdapterRouter 路由到 MLX / oMLX / LiteLLM）──
        from rhythmind.adapters.adapter_router import adapter_router

        # model 参数：None → 读 settings.model_primary_spec（默认 Qwen3-30B-A3B MLX）
        #             显式字符串 → 直接作为 model_spec 使用
        model_spec = model or settings.model_primary_spec or settings.model_primary

        content = await adapter_router.chat(
            final_messages,
            model_spec=model_spec,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        bound_log.debug(
            "call_llm.done model_spec=%s chars=%d",
            model_spec,
            len(content),
        )
        return content

    # ── 便捷方法 ──────────────────────────────────────────────────────────

    async def remember(
        self,
        key: str,
        value: Any,
        mem_type: MemoryType | str = MemoryType.PROJECT,
    ) -> None:
        await self.memory.write(key, value, mem_type)

    async def recall(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return await self.qmd.query_user_memory(
            user_id=self.user_id, query=query, top_k=top_k
        )

    async def search_knowledge(
        self, query: str, collection: str = "health_knowledge"
    ) -> list[dict[str, Any]]:
        return await self.qmd.query(collection=collection, query=query)


# ── 内部工具 ──────────────────────────────────────────────────────────────

def _make_blocked_compliance(reason: str) -> ComplianceResult:
    """构造前置审查 BLOCK 时的 ComplianceResult。"""
    return ComplianceResult(
        level=ComplianceLevel.BLOCK,
        output=None,
        confidence=0.0,
        requires_human_review=True,
        triggered_keywords=[reason],
    )
