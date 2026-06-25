"""
scripts/seed_health_reports.py — Seed 3 份预制健康报告(2026-06-25)

张远舟 3 份健康报告(基于真实佳明数据 + AI 模拟):
- 报告 1: 最新综合报告(2026-05-26)
- 报告 2: 4 周前训练负荷分析(2026-04-30)
- 报告 3: 月度趋势对比(2026-03-15)

存储: health_fact 表(subject=ai_report, predicate=analysis)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text  # noqa: E402

from rhythmind.core.memory.manager import AsyncSessionLocal  # noqa: E402


TEST_USER_ID = "athlete_demo_001"


# 报告 1: 最新综合报告
REPORT_1 = {
    "content": """# 张远舟 健康综合评估报告

> **生成时间**: 2026-05-26
> **数据来源**: Garmin Connect 导出(2022-11 ~ 2026-05)
> **样本量**: 21 个健康事实 + 490 个体能年龄数据点 + 100 个耐力评分

## 一、综合评分

| 维度 | 评分 | 状态 |
|------|------|------|
| **心肺能力** | ⭐⭐⭐⭐⭐ 优秀 | VO2 Max 51(精英级)|
| **训练负荷** | ⭐⭐⭐⭐⭐ 优秀 | ACWR 1.02(科学)|
| **耐力** | ⭐⭐⭐⭐ 上层 | 6759/10000 |
| **跑步表现** | ⭐⭐⭐⭐⭐ 精英 | 5'25"/km 配速 |
| **恢复** | ⚠️ 需关注 | 睡眠质量偏低(深睡 18.5%)|

## 二、核心指标

### 体能
- **VO2 Max**: 51 ml/kg/min(精英跑者阈值 50+)
- **耐力评分**: 6759/10000(classification 4)
- **训练准备度**: 79/100(78% 因子优秀,睡眠因子 37% 拖后)
- **ACWR**: 1.02(急性/慢负荷比,无过训练风险)

### 跑步表现(近 30 天)
- 总跑量:**268.4 km**
- 跑步次数:**32 次**
- 平均配速:**5'25"/km**(精英级)
- 最长一次:**21.1 km**(接近半马距离)

### 恢复指标
- 平均睡眠:**6.8h**(略低于推荐 7-9h)
- 深睡占比:**18.5%**(成人推荐 20-25%)
- 静息心率:数据待补充

## 三、风险评估

### 🔴 高优先级
1. **睡眠时长不足**:6.8h vs 推荐 7-9h,可能影响恢复
2. **深睡占比偏低**:18.5% vs 推荐 20-25%,长期影响生长激素分泌

### 🟡 中优先级
1. **爬坡评分**:29(有提升空间)
2. **训练变化性**:近 6 个月耐力波动 ±500,需关注

### 🟢 优势
1. **训练负荷科学**:ACWR 1.0-1.1 黄金区间
2. **配速持续稳定**:5'25" 维持 12 个月
3. **HRV 健康**:96(优秀范围)

## 四、训练建议

### 短期(1-2 周)
- 睡眠优化:目标 7.5h+,固定作息时间
- 深睡提升:睡前 1h 避免屏幕、室温 18-20°C
- 训练强度:维持当前 ACWR,避免突击

### 中期(1-3 月)
- 爬坡训练:每周 1-2 次坡度跑(8-12% 坡度)
- VO2 突破:间歇训练(4×4min @ 5K 配速 + 3min 恢复)
- 监测重点:睡眠质量、深睡占比

### 长期(2026 年目标)
- 半马 sub-95 分钟(当前配速 5'25" 足够)
- VO2 Max 提升至 55+
- 平均睡眠 7.5h+

## 五、数据可视化建议

- 周跑量趋势图:显示训练变化
- 睡眠 vs 训练准备度散点图
- VO2 Max 长期趋势线
- 训练日历热力图

---

*本报告基于 Garmin 真实数据生成 · 数据截止 2026-05-26*
""",
    "model": "gemma-4-12b-it-4bit (cached)",
    "timestamp": "2026-05-26T08:30:00+00:00",
}

# 报告 2: 4 周前训练负荷分析
REPORT_2 = {
    "content": """# 张远舟 训练负荷专项分析

> **生成时间**: 2026-04-30
> **焦点**: 4 月训练负荷与恢复

## 训练负荷总览

4 月累计训练时间约 12 小时(估算),平均周训练 3 次。
ACWR 维持在 0.95-1.05,处于安全区。

## 重点发现

✅ **训练密度合理**:周 3-4 次,无堆积
✅ **强度分布均衡**:70% 低强度 + 25% 中等 + 5% 高强度
✅ **恢复充足**:每次训练间隔 1-2 天

⚠️ **爬坡训练不足**:4 月仅 2 次坡度跑,建议增至每周 1 次

## 训练负荷分布

| 强度 | 时间 | 占比 |
|------|------|------|
| 恢复跑 | 6.5h | 54% |
| 马拉松配速 | 3h | 25% |
| 阈值跑 | 1.5h | 13% |
| 间歇跑 | 1h | 8% |

## 建议

- 5 月增加 1-2 次坡度跑
- 维持当前 ACWR 区间
- 周末长距离可考虑 25-30 km

---

*本报告基于 Garmin 真实数据生成 · 4 月数据汇总*
""",
    "model": "gemma-4-12b-it-4bit (cached)",
    "timestamp": "2026-04-30T14:20:00+00:00",
}

# 报告 3: 月度趋势对比
REPORT_3 = {
    "content": """# 张远舟 季度趋势对比报告

> **生成时间**: 2026-03-15
> **对比区间**: 2025-Q4 vs 2026-Q1

## VO2 Max 趋势

| 季度 | 平均 | 峰值 | 趋势 |
|------|------|------|------|
| 2025-Q4 | 52.5 | 54 | 基线 |
| 2026-Q1 | 51.0 | 52 | 略降 ⬇ |

3 月略有下降(可能与冬季训练密度降低有关),建议春季逐步提升。

## 跑量趋势

| 月份 | 跑量(km)| 次数 | 配速 |
|------|---------|------|------|
| 2026-01 | 280 | 33 | 5'30" |
| 2026-02 | 265 | 31 | 5'28" |
| 2026-03 | 268 | 32 | 5'25" |

## 关键洞察

1. **跑量稳定**:Q1 月均 271 km,无大幅波动
2. **配速微升**:5'30" → 5'25",有进步趋势
3. **冬训效果**:Q1 配速提升 5s/km

## Q2 训练目标

- 维持月均 270-290 km
- VO2 回升至 53+
- 引入更多坡度训练
- 4 月参加半马测试赛

---

*本报告基于 Garmin 真实数据生成 · Q1 季度数据*
""",
    "model": "gemma-4-12b-it-4bit (cached)",
    "timestamp": "2026-03-15T09:15:00+00:00",
}


async def seed_reports(dry_run: bool = False) -> int:
    """插入 3 份预制健康报告"""
    reports = [
        REPORT_1,
        REPORT_2,
        REPORT_3,
    ]

    if dry_run:
        print(f"[DRY RUN] 将插入 {len(reports)} 份报告 for '{TEST_USER_ID}':")
        for r in reports:
            ts = r["timestamp"]
            preview = r["content"].split("\n")[1].strip("# ")[:60]
            print(f"  - {ts}: {preview}...")
        return len(reports)

    async with AsyncSessionLocal() as session:
        # 1. 清除该用户的旧 ai_report facts
        await session.execute(
            text("""
                UPDATE health_fact
                SET valid_until = :now
                WHERE user_id = :uid
                  AND subject = 'ai_report'
                  AND valid_until IS NULL
            """),
            {"uid": TEST_USER_ID, "now": datetime.now(UTC)},
        )

        # 2. 插入 3 份新报告
        for r in reports:
            obj = {
                "content": r["content"],
                "model": r["model"],
                "timestamp": r["timestamp"],
            }
            obj_json = json.dumps(obj, ensure_ascii=False)
            await session.execute(
                text("""
                    INSERT INTO health_fact
                    (user_id, subject, predicate, object_json, source, confidence, valid_from, valid_until, created_at)
                    VALUES (:uid, 'ai_report', 'analysis', CAST(:obj AS JSONB), 'seed_prefab', 0.90, :vf, NULL, :ca)
                """),
                {
                    "uid": TEST_USER_ID,
                    "obj": obj_json,
                    "vf": datetime.now(UTC),
                    "ca": datetime.now(UTC),
                },
            )

        await session.commit()

    print(f"✅ Seeded {len(reports)} reports for user '{TEST_USER_ID}'")
    return len(reports)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed prefab health reports")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = asyncio.run(seed_reports(dry_run=args.dry_run))
    print(f"\n验证: curl -s -H 'Authorization: Bearer dev' http://localhost:8000/qm/api/reports | jq .reports | length")


if __name__ == "__main__":
    main()