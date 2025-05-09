# ─────────────────────────────────────────────────────────────────────────────
# RHYTHMIND 律动 — Multi-agent AI Health Platform
# 作者：外星动物（常智）/ IoTchange  |  邮箱：14455975@qq.com
# 版权所有 (C) 2024-2025 外星动物（常智）/ IoTchange
# 许可：CC BY-NC 4.0  |  商业授权：14455975@qq.com
# ─────────────────────────────────────────────────────────────────────────────

"""
core/memory/types.py — 记忆类型枚举与数据结构

与系统 prompt 中 auto memory 的四类保持一致：
  user / feedback / project / reference
"""
from __future__ import annotations

from datetime import datetime
import sys
if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    USER = "user"         # 用户画像、偏好、健康背景
    FEEDBACK = "feedback" # Agent 执行结果的正/负反馈
    PROJECT = "project"   # 阶段性目标、当前训练计划
    REFERENCE = "reference"  # 外部数据引用（数据源、指标ID等）


class MemoryEntry(BaseModel):
    """单条记忆条目（写入/读取时的内存表示）"""
    namespace: str        # "user.{user_id}.{agent}.{key}"
    key: str
    value: Any
    mem_type: MemoryType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def build_namespace(
        cls,
        user_id: str,
        agent: str,
        key: str,
    ) -> str:
        """生成标准化命名空间，防止跨用户泄漏。"""
        # 清理特殊字符，只允许 [a-z0-9_-]
        safe = lambda s: "".join(c if c.isalnum() or c in "-_" else "_" for c in s.lower())
        return f"user.{safe(user_id)}.{safe(agent)}.{safe(key)}"


class MemoryRecallResult(BaseModel):
    """recall() 返回的结果集"""
    entries: list[MemoryEntry] = Field(default_factory=list)
    total: int = 0

    def get(self, key: str, default: Any = None) -> Any:
        """按 key 取最新值，兼容 dict.get() 习惯用法。"""
        matched = [e for e in self.entries if e.key == key]
        if not matched:
            return default
        return max(matched, key=lambda e: e.updated_at).value

    def to_dict(self) -> dict[str, Any]:
        return {e.key: e.value for e in self.entries}
