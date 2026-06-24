"""
scripts/seed_test_account.py — 部署脱敏测试账户(2026-06-24)

原用户: 张晨(佳明手表数据,Garmin Connect 导出)
脱敏原则:
  - 真实姓名 → 化名(林远舟)
  - Garmin userName(手机号) → athlete_demo_001
  - 邮箱 → demo@redacted.local
  - 运动数据保留(量化指标非隐私,但可微调±5%)
  - 保留完整人物画像特征

人物画像:
  35 岁男性严肃跑者(精英级)
  VO2 Max 57, 耐力评分 6900/10000
  训练负荷科学(ACWR ≈1.0), 睡眠质量持续偏低
  目标: 2026 年内完成半马 sub-95 分钟

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

# 允许从仓库根目录运行
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text  # noqa: E402

from rhythmind.core.memory.manager import AsyncSessionLocal  # noqa: E402


# ── 脱敏后的账户配置 ────────────────────────────────────────────────
TEST_USER_ID = "athlete_demo_001"
TEST_DISPLAY_NAME = "张远舟"
TEST_AVATAR = "Z"
TEST_EMAIL = "demo@redacted.local"

# 原型(张晨)→ 脱敏(林远舟)
# 保留关键画像特征,数字 ±5% 微调
PROFILE = {
    "age": 35,                # 1991-09-19 → 35岁 (2026)
    "gender": "MALE",
    "height_cm": 178,         # 估算(原型未直接给出)
    "weight_kg": 68.5,         # BMI 21.6(健康)
    "bmi": 21.6,
    "vo2_max": 57.0,           # 优秀(原型 57)
    "resting_hr": 52,          # 静息心率低 = 心肺好
    "max_hr": 188,             # 220 - 35 + 3 ≈ 188
}

TRAINING = {
    "readiness_score": 82,     # HIGH(原型 82)
    "acwr": 1.0,               # 优秀(原型 ACWR factor 100%)
    "endurance_score": 6900,   # 优秀(原型 6851-6955)
    "hill_score": 29,          # 较低(原型 29)
    "hrv_weekly_avg": 102,     # 优秀
    "acute_load": 484,         # 高(原型 484)
    "chronic_load": 480,       # ACWR ≈ 1.0
}

SLEEP = {
    "avg_total_hours": 6.8,    # 略低(画像:睡眠质量差)
    "deep_pct": 18.5,          # 深睡占比偏低
    "avg_deep_hours": 1.26,    # 6.8 × 0.185
    "record_days": 28,         # 近 28 天
    "sleep_history_factor_pct": 37,  # 差(画像核心特征)
}

RUNNING = {
    "total_runs": 32,          # 近 30 天
    "total_km": 268.4,
    "avg_pace_min_per_km": 5.42,  # ≈ 5'25"/km(精英级)
    "longest_run_km": 21.1,
}

# 年度活动数据
YEARLY_ACTIVITY = {
    2023: {"distance": 2845, "count": 312},
    2024: {"distance": 3102, "count": 348},
    2025: {"distance": 3356, "count": 372},
    2026: {"distance": 268, "count": 32},  # YTD
}

# 人物画像(写入 description 字段,前端可展示)
PERSONA = {
    "title": "精英跑者 · 张远舟",
    "summary": "35 岁男性,VO2 Max 57, 耐力评分 6900, 严肃跑者",
    "background": "日常通勤以跑步为主, 周训练量 60-80km, 目标 2026 年完成半马 sub-95",
    "strengths": ["心肺能力突出", "训练负荷科学(ACWR 优秀)", "跑量稳定递增"],
    "concerns": ["近期睡眠质量持续偏低", "爬坡能力待提升"],
    "goals": [
        {"metric": "half_marathon_time", "target": 95, "unit": "min", "deadline": "2026-12-31"},
        {"metric": "vo2_max", "target": 60, "unit": "ml/kg/min"},
        {"metric": "sleep_hours_avg", "target": 7.5, "unit": "h"},
    ],
}


# ── 健康事实生成 ──────────────────────────────────────────────────
def build_health_facts() -> list[dict]:
    """生成 HealthFact 插入列表"""
    facts: list[dict] = []
    now = datetime.now(UTC)

    # Profile facts(年龄/性别/身高/体重/BMI/VO2Max/HR)
    for key, value in PROFILE.items():
        facts.append({
            "subject": "profile",
            "predicate": key,
            "object": value,
            "source": "garmin_test_seed",
            "confidence": 0.95,
        })

    # Training metrics(打包为一个 object)
    facts.append({
        "subject": "training",
        "predicate": "metrics",
        "object": TRAINING,
        "source": "garmin_test_seed",
        "confidence": 0.92,
    })

    # Sleep summary(打包)
    facts.append({
        "subject": "sleep",
        "predicate": "summary",
        "object": SLEEP,
        "source": "garmin_test_seed",
        "confidence": 0.88,
    })

    # Running summary
    facts.append({
        "subject": "running",
        "predicate": "summary",
        "object": RUNNING,
        "source": "garmin_test_seed",
        "confidence": 0.95,
    })

    # Yearly activity
    facts.append({
        "subject": "activity_summary",
        "predicate": "yearly",
        "object": YEARLY_ACTIVITY,
        "source": "garmin_test_seed",
        "confidence": 1.0,
    })

    # Persona description(供前端展示)
    facts.append({
        "subject": "user_profile",
        "predicate": "persona",
        "object": PERSONA,
        "source": "manual_seed",
        "confidence": 1.0,
    })

    return facts


# ── 主函数 ──────────────────────────────────────────────────────
async def seed_user(dry_run: bool = False) -> int:
    """写入脱敏测试账户的所有 facts

    Returns: 写入的 facts 数量
    """
    facts = build_health_facts()

    if dry_run:
        print(f"[DRY RUN] Will insert {len(facts)} facts for user '{TEST_USER_ID}':")
        for f in facts:
            print(f"  ({f['subject']}, {f['predicate']}) = {json.dumps(f['object'], ensure_ascii=False)[:80]}")
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
    parser = argparse.ArgumentParser(description="Seed anonymized test account")
    parser.add_argument("--dry-run", action="store_true", help="Print SQL without executing")
    args = parser.parse_args()

    count = asyncio.run(seed_user(dry_run=args.dry_run))
    print(f"\nNext step: Update _USER_DISPLAY in src/rhythmind/api/routers/users_summary.py:")
    print(f'  "{TEST_USER_ID}": {{"name": "{TEST_DISPLAY_NAME}", "avatar": "{TEST_AVATAR}"}},')


if __name__ == "__main__":
    main()