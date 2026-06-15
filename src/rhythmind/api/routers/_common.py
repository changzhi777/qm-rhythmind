"""
api/routers/_common.py — dashboard 系列路由共享工具

提供：
  - _fm(user_id) — FactManager 工厂（被 dashboard / reports / users_summary 共享）
"""
from __future__ import annotations

from rhythmind.core.memory.fact_manager import FactManager


def _fm(user_id: str) -> FactManager:
    """创建指定用户的 FactManager 实例。"""
    return FactManager(user_id)
