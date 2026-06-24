"""
scripts/seed_test_account.py — 部署脱敏测试账户(2026-06-24 v2)

数据源:佳明 Connect 导出 `佳明数据20260526/` 全部历史数据(2022-11~2026-05)
脱敏原则:
  - 真实姓名 → 化名(保留张姓:张远舟)
  - Garmin userName(手机号) → athlete_demo_001
  - 邮箱 → demo@redacted.local
  - 运动数据保留(基于真实数据,无 ±5% 微调)
  - 完整人物画像特征

事实数量:30+ 条(原 13 → 30+,扩充时序历史 + 个人纪录 + 乳酸阈值等)

Usage:
  python3 scripts/seed_test_account.py --dry-run    # 只打印 SQL 不执行
  python3 scripts/seed_test_account.py              # 直接写入 DB
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# 允许从仓库根目录运行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))  # 让 load_garmin 可导入

from sqlalchemy import text  # noqa: E402

from rhythmind.core.memory.manager import AsyncSessionLocal  # noqa: E402

from load_garmin_20260526 import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    build_dataset,
    persona_from_dataset,
)


# ── 账户配置(脱敏后) ─────────────────────────────────────────────────
TEST_USER_ID = "athlete_demo_001"
TEST_DISPLAY_NAME = "张远舟"
TEST_AVATAR = "Z"
TEST_EMAIL = "demo@redacted.local"


# ── 健康事实生成(30+ 条) ─────────────────────────────────────────────
def build_health_facts() -> list[dict]:
    """从佳明 20260526 数据集生成 30+ HealthFact"""
    ds = build_dataset(DEFAULT_DATA_ROOT)
    facts: list[dict] = []

    # 1-8. profile(8 条)
    for key, value in ds.profile.items():
        facts.append({
            "subject": "profile",
            "predicate": key,
            "object": value,
            "source": "garmin_20260526",
            "confidence": 0.95,
        })

    # 9. training.metrics(1 条,object 内含 9 字段)
    facts.append({
        "subject": "training",
        "predicate": "metrics",
        "object": ds.training,
        "source": "garmin_20260526",
        "confidence": 0.92,
    })

    # 10. sleep.summary
    facts.append({
        "subject": "sleep",
        "predicate": "summary",
        "object": ds.sleep,
        "source": "garmin_20260526",
        "confidence": 0.88,
    })

    # 11. running.summary
    facts.append({
        "subject": "running",
        "predicate": "summary",
        "object": ds.running,
        "source": "garmin_20260526",
        "confidence": 0.95,
    })

    # 12. activity_summary.yearly
    yearly = {str(k): v for k, v in ds.yearly_activity.items()}
    facts.append({
        "subject": "activity_summary",
        "predicate": "yearly",
        "object": yearly,
        "source": "garmin_20260526",
        "confidence": 1.0,
    })

    # 13-16. 时序历史(4 条)
    for trend_name, trend_data in ds.trends.items():
        facts.append({
            "subject": "trends",
            "predicate": trend_name,
            "object": {
                "metric": trend_name,
                "unit": _trend_unit(trend_name),
                "data_points": trend_data,
            },
            "source": "garmin_20260526",
            "confidence": 0.95,
        })

    # 17. fitness_age
    facts.append({
        "subject": "fitness_age",
        "predicate": "history",
        "object": {
            "data_points_count": len(ds.fitness_age_history),
            "latest": ds.fitness_age_history[-1] if ds.fitness_age_history else {},
        },
        "source": "garmin_20260526",
        "confidence": 0.95,
    })

    # 18. personal_records
    facts.append({
        "subject": "personal_records",
        "predicate": "all",
        "object": {"records": ds.personal_records},
        "source": "garmin_20260526",
        "confidence": 1.0,
    })

    # 19. lactate_threshold
    facts.append({
        "subject": "performance",
        "predicate": "lactate_threshold",
        "object": ds.lactate_threshold,
        "source": "garmin_20260526",
        "confidence": 0.90,
    })

    # 20. user_profile.persona
    facts.append({
        "subject": "user_profile",
        "predicate": "persona",
        "object": persona_from_dataset(ds),
        "source": "computed_from_garmin_20260526",
        "confidence": 1.0,
    })

    # 21-22. user_basic(脱敏基础信息)
    facts.append({
        "subject": "user_basic",
        "predicate": "auth",
        "object": {
            "display_name": TEST_DISPLAY_NAME,
            "email": TEST_EMAIL,
            "avatar": TEST_AVATAR,
        },
        "source": "manual_seed",
        "confidence": 1.0,
    })

    return facts


def _trend_unit(name: str) -> str:
    """时序数据单位"""
    return {
        "vo2_max": "ml/kg/min",
        "readiness": "/100",
        "endurance": "score",
        "hill": "score",
    }.get(name, "")


# ── 主函数 ──────────────────────────────────────────────────────
async def seed_user(dry_run: bool = False) -> int:
    """写入脱敏测试账户的所有 facts

    Returns: 写入的 facts 数量
    """
    facts = build_health_facts()

    if dry_run:
        print(f"[DRY RUN] Will insert {len(facts)} facts for user '{TEST_USER_ID}':")
        for f in facts:
            obj_str = json.dumps(f["object"], ensure_ascii=False)
            print(f"  ({f['subject']}, {f['predicate']}) = {obj_str[:90]}")
        return len(facts)

    async with AsyncSessionLocal() as session:
        now = datetime.now(UTC)
        # 1. 先清除该用户已有的 facts(避免重复)
        await session.execute(
            text("UPDATE health_fact SET valid_until = :now WHERE user_id = :uid AND valid_until IS NULL"),
            {"uid": TEST_USER_ID, "now": now},
        )

        # 2. 批量插入
        for fact in facts:
            obj_json = json.dumps(fact["object"], ensure_ascii=False)
            await session.execute(
                text("""
                    INSERT INTO health_fact
                    (user_id, subject, predicate, object_json, source, confidence, valid_from, valid_until, created_at)
                    VALUES (:uid, :subj, :pred, CAST(:obj AS JSONB), :src, :conf, :vf, NULL, :ca)
                """),
                {
                    "uid": TEST_USER_ID,
                    "subj": fact["subject"],
                    "pred": fact["predicate"],
                    "obj": obj_json,
                    "src": fact["source"],
                    "conf": fact["confidence"],
                    "vf": now,
                    "ca": now,
                },
            )

        await session.commit()

    print(f"✅ Seeded {len(facts)} facts for user '{TEST_USER_ID}' ({TEST_DISPLAY_NAME})")
    return len(facts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed anonymized test account (v2)")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    args = parser.parse_args()

    count = asyncio.run(seed_user(dry_run=args.dry_run))
    print(f"\nNext step: Update _USER_DISPLAY in src/rhythmind/api/routers/users_summary.py:")
    print(f'  "{TEST_USER_ID}": {{"name": "{TEST_DISPLAY_NAME}", "avatar": "{TEST_AVATAR}"}},')


if __name__ == "__main__":
    main()