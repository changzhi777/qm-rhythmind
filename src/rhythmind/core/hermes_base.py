# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/hermes_base.py — HermesBase：所有 Agent 的抽象基类

四步闭环（Hermes Pattern v2，精简版）：
  1. retrieve_memory  — 从 MemoryManager 召回历史上下文
  2. execute          — 子类实现具体业务逻辑（抽象方法）
     └─ call_llm()   — 透明 prompt 审查：gemma-4-e4b 本地预检
  3. compliance_check — ComplianceGate 三级输出分级（output 后置检查）
  4. update_memory    — 沉淀经验、更新记忆

合规双层防护：
  前置（call_llm 内）— gemma-4-e4b 审查 prompt 意图，拦截危险请求
  后置（Step 3）    — ComplianceGate 关键词扫描 + 置信度分级

设计约束：
  - 全链路 async/await，禁止 sync I/O
  - call_llm() 审查超时或 gemma 不可用 → 降级放行，主流程不中断
  - 审查 BLOCK → raise ComplianceBlockedError（在 execute 内捕获或上抛）
  - 每步均有 structlog 埋点，便于 OpenTelemetry 采集
"""
from __future__ import annotations

import json
import re
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


# ── 工具函数：鲁棒 JSON 提取 ─────────────────────────────────────────────

# 思考型模型常输出"自由文本 + JSON 块"或"```json ... ```"格式
# 直接 json.loads(content) 失败，需要先剥离/提取。

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(content: str) -> str:
    """
    从可能包含思考文本的模型输出中提取顶层 JSON 对象。

    策略（按优先级）：
      1. 尝试 strict json.loads — 已是纯 JSON 直接返回
      2. 匹配 markdown ```json ... ``` 代码块
      3. 从第一个 '{' 起做括号配对，定位匹配的 '}'，截取并校验
      4. 全部失败 → 返回原 content（让下游 json.loads 抛错暴露问题）

    兼容 Qwen3 / DeepSeek-R1 / o1 等带 thinking 的模型。
    """
    if not content:
        return content

    stripped = content.strip()
    # 1. 已经是纯 JSON
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            json.loads(stripped)
            return stripped
        except (json.JSONDecodeError, ValueError):
            pass

    # 2. markdown 代码块
    m = _FENCE_RE.search(content)
    if m:
        candidate = m.group(1)
        try:
            json.loads(candidate)
            return candidate
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. 括号配对定位顶层 JSON
    start = content.find("{")
    if start < 0:
        return content

    depth = 0
    in_string = False
    escape_next = False
    for i in range(start, len(content)):
        c = content[i]
        if escape_next:
            escape_next = False
            continue
        if c == "\\" and in_string:
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                candidate = content[start:i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except (json.JSONDecodeError, ValueError):
                    return content  # 找到边界但内容非法 — 让下游报错

    return content  # 没找到完整 JSON — 让下游 json.loads 抛错


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
        self.compliance = ComplianceGate()
        self.auditor = PromptAuditor()

        self._log = log.bind(agent=agent_name, user_id=user_id)

    # ── 四步闭环主入口 ────────────────────────────────────────────────────

    async def run(self, ctx: AgentContext) -> HermesRunResult:
        """
        四步闭环主入口。

        Step 2 内部通过 call_llm() 触发前置合规审查（gemma-4-e4b）。
        Step 3 对输出做后置关键词扫描（ComplianceGate）。
        两层独立，互不依赖。
        """
        t0 = time.perf_counter()
        bound_log = self._log.bind(session=ctx.session_id, task=ctx.task_type)
        last_audit: AuditResult | None = None

        # ── Step 1: 召回历史记忆 ──────────────────────────────────────────
        bound_log.debug("hermes.run step=1 recall_memory")
        memory_ctx: MemoryRecallResult = await self.memory.recall(ctx.task_type)

        # ── Step 2: 执行业务逻辑（call_llm 内含前置审查）────────────────
        bound_log.debug("hermes.run step=2 execute")
        try:
            raw_result: AgentResult = await self.execute(ctx, memory_ctx)
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

        # ── Step 3: 后置合规检查（output 关键词扫描）────────────────────
        bound_log.debug("hermes.run step=3 compliance_check")
        checked: ComplianceResult = self.compliance.validate(raw_result)

        if checked.level == ComplianceLevel.BLOCK:
            checked.compliance_block = True
            bound_log.warning(
                "hermes.run output_BLOCKED kws=%s", checked.triggered_keywords
            )
        if raw_result.requires_human_review:
            checked.advisor_review = True
            bound_log.warning("hermes.run advisor_review_requested")
            latency_ms = (time.perf_counter() - t0) * 1000
            return HermesRunResult(
                compliance=checked,
                agent=self.agent_name,
                user_id=self.user_id,
                task_type=ctx.task_type,
                latency_ms=latency_ms,
                audit_result=last_audit,
            )

        # ── Step 4: 更新记忆 ─────────────────────────────────────────────
        bound_log.debug("hermes.run step=4 update_memory")
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

        # ── JSON 输出归一化（兼容不支持 response_format 的模型）─────────
        # 部分模型（尤其 Qwen3 thinking 模式）会输出"思考文本 + JSON"混合内容，
        # 直接 json.loads() 失败。请求方指定 json_object 时做一次鲁棒提取。
        if response_format and response_format.get("type") == "json_object":
            content = _extract_json_object(content)

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


# ── 内部工具 ──────────────────────────────────────────────────────────────

def _make_blocked_compliance(reason: str) -> ComplianceResult:
    """构造前置审查 BLOCK 时的 ComplianceResult。"""
    return ComplianceResult(
        level=ComplianceLevel.BLOCK,
        output=None,
        confidence=0.0,
        compliance_block=True,
        triggered_keywords=[reason],
    )
