"""
api/routers/users_summary.py — 多用户首页选择卡片 API

端点：
  GET /qm/api/users/summary — 返回所有用户的健康数据摘要（首页用户选择卡片用）
"""
from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qm/api", tags=["users"])


_USER_DISPLAY: dict[str, dict[str, str]] = {
    "garmin_user_001": {"name": "律动跑者", "avatar": "M"},
    "athlete_zhang": {"name": "张晓燕", "avatar": "Z"},
    # 2026-06-24 脱敏测试账户(基于佳明"张晨"原型,化名林远舟)
    "athlete_demo_001": {"name": "林远舟", "avatar": "L"},
}


@router.get("/users/summary")
async def get_users_summary() -> dict[str, Any]:
    """返回所有用户的健康数据摘要（首页用户选择卡片用）。"""
    from sqlalchemy import text

    from rhythmind.core.memory.manager import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        # 1. 批量获取用户及其 facts 计数
        result = await session.execute(text(
            "SELECT user_id, COUNT(*) as cnt FROM health_fact "
            "WHERE valid_until IS NULL GROUP BY user_id"
        ))
        user_counts = {row[0]: row[1] for row in result.all()}

        # 2. 批量获取 profile（age/bmi/vo2_max/weight_kg/gender）
        result = await session.execute(text(
            "SELECT user_id, predicate, object_json FROM health_fact "
            "WHERE valid_until IS NULL AND subject = 'profile' "
            "AND predicate IN ('age','bmi','vo2_max','weight_kg','gender')"
        ))
        profiles: dict[str, dict[str, Any]] = {}
        for uid, pred, obj in result.all():
            profiles.setdefault(uid, {})
            if isinstance(obj, str):
                with contextlib.suppress(Exception):
                    obj = json.loads(obj)
            profiles[uid][pred] = obj

        # 3. 批量获取 running summary
        result = await session.execute(text(
            "SELECT user_id, object_json FROM health_fact "
            "WHERE valid_until IS NULL AND subject = 'running' AND predicate = 'summary'"  # noqa: E501
        ))
        running_map: dict[str, dict[str, Any]] = {}
        for uid, obj in result.all():
            if isinstance(obj, str):
                with contextlib.suppress(Exception):
                    obj = json.loads(obj)
            if isinstance(obj, dict):
                running_map[uid] = obj

        # 4. 批量获取 medical 统计
        has_medical_users: set[str] = set()
        active_meds_map: dict[str, int] = {}
        abnormal_labs_map: dict[str, int] = {}
        try:
            result = await session.execute(text(
                "SELECT user_id FROM med_patient_profile"
            ))
            has_medical_users = {row[0] for row in result.all()}

            result = await session.execute(text(
                "SELECT user_id, COUNT(*) FROM med_medication "
                "WHERE status = 'active' GROUP BY user_id"
            ))
            active_meds_map = {row[0]: row[1] for row in result.all()}

            result = await session.execute(text(
                "SELECT user_id, COUNT(*) FROM med_lab_result "
                "WHERE flag IS NOT NULL GROUP BY user_id"
            ))
            abnormal_labs_map = {row[0]: row[1] for row in result.all()}
        except Exception:
            pass

        # 5. 组装结果
        users_data = []
        for uid, facts_count in user_counts.items():
            display = _USER_DISPLAY.get(uid, {"name": uid, "avatar": "?"})
            users_data.append({
                "user_id": uid,
                "display_name": display["name"],
                "avatar": display["avatar"],
                "facts_count": facts_count,
                "has_medical": uid in has_medical_users,
                "profile": profiles.get(uid, {}),
                "running": running_map.get(uid, {}),
                "active_medications": active_meds_map.get(uid, 0),
                "abnormal_labs": abnormal_labs_map.get(uid, 0),
            })

    return {"status": "ok", "users": users_data}
