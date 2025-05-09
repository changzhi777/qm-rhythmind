# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/skill/extractor.py — 技能自动提取器

从 AgentContext + ComplianceResult 中提取值得沉淀的技能片段。

技能提取策略：
  1. 高置信度（>= 0.85）的成功执行结果 → 提取模板
  2. skill_candidates 字段（Agent 主动标注）→ 直接采纳
  3. LLM 提取（复杂场景，调用 fast 模型）→ 可选，按需开启

输出格式遵循 SKILL.md 约定：
  ## skill_name
  **触发条件**: ...
  **操作步骤**: ...
  **注意事项**: ...
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 只有置信度高于此值的结果才考虑提取技能
_SKILL_EXTRACT_THRESHOLD = 0.85


class SkillExtractor:
    """
    规则驱动的技能提取器（无 LLM 调用，低延迟）。

    Phase 2 可扩展为 LLM 辅助提取。
    """

    def extract(
        self,
        task_type: str,
        skill_candidates: list[str],
        output: Any,
        confidence: float,
        agent: str,
    ) -> list[dict[str, str]]:
        """
        提取技能条目。

        Returns:
            [{"id": str, "content": str, "agent": str, "task_type": str}, ...]
        """
        results: list[dict[str, str]] = []

        if confidence < _SKILL_EXTRACT_THRESHOLD:
            logger.debug(
                "skill.extract skip: confidence=%.2f < threshold=%.2f",
                confidence, _SKILL_EXTRACT_THRESHOLD,
            )
            return results

        # Agent 主动标注的技能候选
        for candidate in skill_candidates:
            content = self._format_skill(candidate, task_type, agent)
            results.append({
                "id": self._skill_id(agent, content),
                "content": content,
                "agent": agent,
                "task_type": task_type,
            })

        if results:
            logger.info(
                "skill.extract agent=%s task=%s extracted=%d",
                agent, task_type, len(results),
            )
        return results

    @staticmethod
    def _format_skill(candidate: str, task_type: str, agent: str) -> str:
        """将候选字符串格式化为 SKILL.md 条目。"""
        return (
            f"## {candidate}\n"
            f"**Agent**: {agent}\n"
            f"**触发条件**: task_type = {task_type}\n"
            f"**说明**: 自动提取自高置信度执行结果\n"
        )

    @staticmethod
    def _skill_id(agent: str, content: str) -> str:
        h = hashlib.sha256(f"{agent}:{content}".encode()).hexdigest()[:16]
        return f"skill_{agent}_{h}"
