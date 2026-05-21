# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/compliance/prompt_auditor.py — Gemma-4-E4B 本地 Prompt 合规审查器

调用时机：HermesBase.call_llm() → 主模型调用之前
数据流：  messages → gemma-4-e4b(本地) → AuditResult → 决策

设计约束：
  1. 数据零外泄：gemma 运行在本机 oMLX，不走互联网
  2. 轻量 prompt：只需输出 JSON 风险评估，max_tokens=512
  3. 超时降级：gemma 超时或不可用 → AuditResult.level=PASS（宁放行勿阻断）
  4. 不替代 output 合规：这是"前置拦截"，后置 ComplianceGate 仍保留

审查维度（gemma 评估）：
  medical_risk   — 是否引导生成医疗诊断/处方
  privacy_risk   — 是否暴露或要求用户私密信息
  hallucination  — prompt 是否诱导虚假健康数据
  overall_score  — 综合风险分（0.0 安全 ~ 1.0 高危）

判定规则：
  overall_score >= block_score (0.75) → BLOCK
  overall_score >= warn_score  (0.40) → WARN（主模型继续，增加系统约束）
  overall_score <  warn_score         → PASS
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rhythmind.config import settings

logger = logging.getLogger(__name__)


class AuditLevel(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass
class AuditResult:
    level: AuditLevel
    overall_score: float = 0.0
    medical_risk: float = 0.0
    privacy_risk: float = 0.0
    hallucination_risk: float = 0.0
    reason: str = ""
    extra_constraints: list[str] = field(default_factory=list)
    # 审查器是否正常运行（False = 降级放行）
    auditor_available: bool = True

    @property
    def blocked(self) -> bool:
        return self.level == AuditLevel.BLOCK

    @property
    def warned(self) -> bool:
        return self.level == AuditLevel.WARN


# ── Gemma 审查 prompt 模板 ─────────────────────────────────────────────────

_AUDIT_SYSTEM = """\
你是律动健康 AI 平台的安全审查员。
你的任务是评估一段即将发送给 AI 助手的对话，判断它是否存在医疗合规风险。

请只输出以下 JSON，不要有任何其他内容：
{
  "medical_risk": 0.0~1.0,       // 是否诱导生成医疗诊断/处方/用药建议
  "privacy_risk": 0.0~1.0,       // 是否涉及敏感个人健康隐私泄露
  "hallucination_risk": 0.0~1.0, // 是否可能诱导输出虚假健康数据
  "overall_score": 0.0~1.0,      // 综合风险评分
  "reason": "简要说明（中文，20字以内）",
  "extra_constraints": ["如需要则列出应追加的系统约束"]
}

评分基准：
  0.0~0.2  安全，无明显风险
  0.2~0.4  轻微，注意措辞
  0.4~0.75 中等，需追加约束
  0.75~1.0 高危，应拦截
"""


def _build_audit_prompt(messages: list[dict[str, Any]]) -> str:
    """将 messages 列表转为可供 gemma 审查的文本。"""
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, list):
            # 多模态 content（取文本部分）
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        lines.append(f"[{role}]: {content[:500]}")  # 截断超长内容
    return "\n".join(lines)


class PromptAuditor:
    """
    本地合规审查器（默认使用 gemma-4-e4b-it-4bit via OMLXAdapter）。

    无状态，可在多 Agent 间共享同一实例。
    通过 OMLXAdapter 调用本地 oMLX，数据零外泄。

    model_spec 格式遵循 AdapterRouter 规范：
      "omlX://gemma-4-e4b-it-4bit"  → OMLXAdapter（默认）
      "mlx://..."                  → MLXAdapter（如果把审查模型换成 MLX 本地模型）
    """

    def __init__(self, model_spec: str | None = None) -> None:
        self._block_score = settings.compliance_audit_block_score
        self._warn_score = settings.compliance_audit_warn_score
        self._timeout = settings.compliance_audit_timeout
        self._enabled = settings.compliance_audit_enabled
        # 审查模型 spec：默认读 settings.model_compliance_spec
        self._model_spec: str = (
            model_spec or settings.model_compliance_spec or
            f"omlX://{settings.model_compliance}"
        )

    def _get_adapter(self):
        """懒获取 Adapter 实例（避免模块级导入触发副作用）。"""
        from rhythmind.adapters.adapter_router import adapter_router
        return adapter_router.get(self._model_spec)

    async def audit(
        self,
        messages: list[dict[str, Any]],
    ) -> AuditResult:
        """
        对即将发送给主模型的 messages 进行风险评估。

        Returns:
            AuditResult — 包含风险分数和判定等级
        """
        if not self._enabled:
            return AuditResult(level=AuditLevel.PASS, auditor_available=False)

        audit_text = _build_audit_prompt(messages)
        audit_messages = [
            {"role": "system", "content": _AUDIT_SYSTEM},
            {"role": "user", "content": f"请审查以下对话：\n\n{audit_text}"},
        ]

        try:
            adapter = self._get_adapter()
            raw = await asyncio.wait_for(
                adapter.chat(
                    audit_messages,
                    temperature=0.1,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                ),
                timeout=self._timeout,
            )
            return self._parse_response(raw)

        except TimeoutError:
            # Python 3.10: asyncio.TimeoutError ≠ built-in TimeoutError；同时捕获两者
            logger.warning(
                "prompt_auditor.timeout after=%.1fs fallback=PASS", self._timeout
            )
            return AuditResult(
                level=AuditLevel.PASS,
                reason="审查器超时，降级放行",
                auditor_available=False,
            )
        except Exception as e:
            logger.warning("prompt_auditor.error=%s fallback=PASS", e)
            return AuditResult(
                level=AuditLevel.PASS,
                reason=f"审查器不可用：{type(e).__name__}",
                auditor_available=False,
            )

    def _parse_response(self, raw: str) -> AuditResult:
        """解析 gemma 输出的 JSON 风险评估。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("prompt_auditor.parse_error raw=%r fallback=PASS", raw[:100])
            return AuditResult(level=AuditLevel.PASS, reason="解析失败，降级放行")

        overall = float(data.get("overall_score", 0.0))
        medical = float(data.get("medical_risk", 0.0))
        privacy = float(data.get("privacy_risk", 0.0))
        hallucination = float(data.get("hallucination_risk", 0.0))
        reason = str(data.get("reason", ""))
        extra = list(data.get("extra_constraints", []))

        # 判定等级
        if overall >= self._block_score:
            level = AuditLevel.BLOCK
            logger.warning(
                "prompt_auditor.BLOCK score=%.2f reason=%s", overall, reason
            )
        elif overall >= self._warn_score:
            level = AuditLevel.WARN
            logger.info(
                "prompt_auditor.WARN score=%.2f reason=%s", overall, reason
            )
        else:
            level = AuditLevel.PASS
            logger.debug("prompt_auditor.PASS score=%.2f", overall)

        return AuditResult(
            level=level,
            overall_score=overall,
            medical_risk=medical,
            privacy_risk=privacy,
            hallucination_risk=hallucination,
            reason=reason,
            extra_constraints=extra,
            auditor_available=True,
        )
