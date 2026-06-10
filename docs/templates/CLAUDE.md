# CLAUDE.md — docs/templates

> 🧭 [工作空间](../../../CLAUDE.md) > [qm-rhythmind](../../CLAUDE.md) > [docs](../) > **templates**

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 目录说明

存放标准化报告模板，供生成各类健康数据分析报告时参考。

---

## 文件清单

| 文件 | 说明 | 行数 |
|------|------|------|
| `garmin-health-report-template.md` | 佳明健康数据报告模板 v1.0 — 三种格式章节结构、字段映射、SpO2 分析代码 | 196 |

---

## 使用场景

当用户上传 Garmin Connect 导出数据时，参照本模板生成报告，确保格式统一、数据完整。

---

## 三种报告格式对比

| 维度 | 通俗解读版 | 专业分析版 | 可视化页面 (HTML) |
|------|-----------|-----------|-------------------|
| 目标读者 | 用户本人 | 教练/医生 | 全用户 |
| 章节数 | 10 章 | 12 章 | 7 图表 |
| 写作风格 | 比喻、大白话 | 精确数值、专业术语 | 暗色仪表盘 |
| 核心指标 | 趋势 + 行动建议 | 参考范围 + 百分比 | SVG 内联图表 |
| 输出格式 | MD → PDF | MD → PDF | HTML → A4 PDF |
| SpO2 分析 | 重点强调 + 通俗解释 | 夜间分布 + OSA 筛查 | 月度趋势图 |

### 章节映射对照

| 通俗解读版 | 专业分析版 | 可视化页面 |
|-----------|-----------|-----------|
| 前言: 写在前面 | — | — |
| 1: 身体基本情况 | 2: 用户档案 | 用户画像卡片 |
| 2: 体能评估 | 3: 核心体能 | VO2Max 仪表盘 |
| 3: 赛事预测 | 4: 赛事预测 | 赛事预测卡片 |
| 4: 训练规律性 | 5: 训练负荷 | ACWR 分布图、训练指标卡片 |
| 5: 睡眠分析 | 6: 睡眠分析 | 睡眠饼图 + 指标卡片 |
| 6: 白天健康状态 | 7: 健康监测 | — |
| 7: 心率区间 | — | 心率区间柱状图 |
| 8: 总结与行动 | 9: 分阶段方案、12: 优先级矩阵 | — |
| 9: 饮食恢复建议 | 11: 饮食恢复 | — |
| 10: 一句话总结 | 1: 执行摘要 | — |
| — | 8: 风险评估 | — |
| — | 10: 监测清单 | — |

---

## 字段对照表

### 用户元信息字段

| 模板变量 | Garmin 数据来源 | 字段路径 | 类型 | 必填 |
|---------|----------------|---------|------|------|
| `姓名` | `user.json` | `firstName` + `lastName` | string | ✅ |
| `性别` | `user.json` | `gender` | enum(MALE/FEMALE) | ✅ |
| `年龄` | `user.json` | `birthDate` → 计算年龄 | number | ✅ |
| `身高` | `user.json` | `height` | float (cm) | ✅ |
| `体重` | `weight.json` | `weight` (最新值) | float (kg) | ✅ |
| `数据时间跨度` | 所有文件时间戳 | min/max timestamp | date range | ✅ |
| `报告日期` | 系统时间 | `datetime.now()` | date | ✅ |
| `运动次数` | `activities.json` | 自动统计 | number | ⬜ |
| `睡眠晚数` | `sleepData*.json` | 自动统计 | number | ⬜ |

### 核心生理指标字段

| 模板变量 | Garmin 数据来源 | 关键字段 | 正常范围 | 预警阈值 | 通俗解读映射 |
|---------|----------------|---------|---------|---------|-------------|
| `BMI` | `weight.json` | weight / (height_m)² | 18.5-24.9 | >24.9 | "体重指数" |
| `resting_hr` | `user.json` / 手表采集 | `restingHeartRate` | 60-100 bpm | <50 或 >100 | "静息心率=发动机怠速" |
| `vo2_max` | `FitnessAge` JSON | `vo2Max` | 年龄+性别相关 | <同龄25%分位 | "体能发动机排量" |
| `fitness_age` | `FitnessAge` JSON | `fitnessAge` | ≤实际年龄 | >实际年龄+5 | "身体年龄 vs 身份证年龄" |
| `weight` | `weight.json` | `weight` (最新值) | — | BMI>24.9 需减重 | — |

### 训练指标字段

| 模板变量 | Garmin 数据来源 | 关键字段 | 计算方式 | 正常范围 | 预警阈值 |
|---------|----------------|---------|---------|---------|---------|
| `acwr` | `TrainingStatus/metrics/` | `acwr` | acuteLoad(7d)/chronicLoad(28d) | 0.8-1.3 | >1.5 受伤风险 |
| `acute_load` | `TrainingStatus/metrics/` | `acuteLoad` | 7天训练负荷总和 | — | — |
| `chronic_load` | `TrainingStatus/metrics/` | `chronicLoad` | 28天训练负荷平均 | — | — |
| `readiness_score` | `TrainingReadiness/` | `score` | 手表综合评分 | ≥70 | <40 不建议高强度 |
| `endurance_score` | 手表推算 | `enduranceScore` | 基于VO2Max+训练历史 | — | — |
| `hill_score` | 手表推算 | `hillScore` | 爬坡能力评分 | — | — |
| `hrv_status` | `HeartRateVariability/` | `weeklyAvg` | 7天HRV均值 | 个体基线相关 | 连续7天低于基线 |
| `race_predictions` | `RacePredictions/` | `time` per `distance` | 手表Garmin算法 | — | — |

### 睡眠与SpO2字段

| 模板变量 | Garmin 数据来源 | 关键字段 | 单位 | 正常范围 | OSA 筛查标准 |
|---------|----------------|---------|------|---------|-------------|
| `sleep_duration` | `sleepData*.json` | `sleepTimeSeconds` | 小时 | 7-9h | <6h 睡眠不足 |
| `deep_sleep` | `sleepData*.json` | `deepSleepSeconds` | 小时/百分比 | 15-25% | <12% 深睡不足 |
| `rem_sleep` | `sleepData*.json` | `remSleepSeconds` | 小时/百分比 | 20-25% | <15% 需关注 |
| `sleep_score` | `sleepData*.json` | `sleepScores.overall.value` | 0-100 | ≥75 | <60 睡眠质量差 |
| `avg_spo2` | `sleepData*.json` | `avgSpO2` | % | ≥95% | <90% 低氧事件 |
| `min_spo2` | `sleepData*.json` | `minSpO2` | % | ≥90% | <80% 严重低氧 |
| `avg_respiration` | `sleepData*.json` | `avgRespiration` | 次/分 | 12-20 | >20 需关注 |
| `hypoxic_nights` | — | 计算: `minSpO2 < 90` 的夜晚数 | 次 | 0 | >30%夜晚为 HIGH RISK |
| `osa_risk` | — | 计算: `hypoxic_ratio > 0.3` | enum | NORMAL | HIGH (需多导睡眠监测) |

### SpO2 分级统计

| 分级 | avgSpO2 范围 | 含义 | 通俗解读措辞 |
|------|-------------|------|-------------|
| 正常 | ≥95% | 血氧正常 | "睡眠期间大脑供氧充足" |
| 轻度偏低 | 90-94% | 需关注 | "部分夜晚血氧偏低，注意观察" |
| 中度偏低 | 85-89% | 建议就医 | "血氧多次低于正常，建议做睡眠监测" |
| 严重偏低 | <85% | 立即就医 | "⚠ 严重低氧，请尽快到呼吸科就诊" |

---

## 图表规格（HTML 可视化版）

| 图表 | 类型 | SVN 元素 | 数据聚合粒度 | 配色 |
|------|------|---------|-------------|------|
| VO2Max 趋势 | 折线+面积 | `polyline` + `fill` | 按时间戳 | `#42a5f5 → #1a237e` 渐变 |
| 睡眠月度趋势 | 柱状图 | `rect` | 按月均值 | `#7e57c2` 深睡 / `#5c6bc0` REM |
| 睡眠质量分布 | 环形图 | `circle` + `stroke-dasharray` | 评分分档统计 | 5 色分段 |
| 近14晚睡眠 | 分组柱状图 | `rect` 组 | 逐日明细 | 同月度趋势 |
| ACWR 分布 | 横向条形图 | `rect` | 30天分档 | 绿(0.8-1.3) / 黄(1.3-1.5) / 红(>1.5) |
| 耐力评分趋势 | 折线图 | `polyline` | 按时间戳 | `#66bb6a` |
| 训练准备度 | 面积图 | `polyline` + `fill` | 按时间戳 | 渐变填充 |

---

## PDF 生成参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 引擎 | Playwright `page.pdf()` | Chromium headless |
| 纸张 | A4 (210×297mm) | — |
| 边距 | 上14 / 下14 / 左12 / 右12 mm | — |
| 页眉 | `RHYTHMIND 律动 · {title}` | 8px #aaa |
| 页脚 | `第 X / Y 页` | 8px #aaa |
| 背景 | `print_background=True` | 保留暗色主题 |

---

## 报告尾部模板

```markdown
---
*本报告基于佳明手表自动采集数据生成，仅供健康管理参考，不构成医学诊断。如有持续不适，请及时就医。*
*湖南青沐生命科技有限公司 · RHYTHMIND 律动 AI 健康管理平台 · YYYY年M月D日*
```

### 数据质量说明（报告必附）

| # | 说明 | 影响 |
|---|------|------|
| 1 | 活动距离可能为累积值 | 单次活动距离偏大，需用 `summarizedActivitiesExport` |
| 2 | 手表不合并午睡/分段睡眠 | 实际睡眠可能长于记录 |
| 3 | 腕式 SpO2 精度有限 | 低值需医疗设备确认（AHI ≥5 + SpO2<90% 建议 PSG） |
| 4 | 体重依赖手动输入 | 如无智能体脂秤，BMI 可能有偏差 |

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：新增字段对照表（3 类 × 30+ 字段）、SpO2 分级统计、图表规格、PDF 参数、三种格式章节映射
- **2026-05-27** 首次 AI 上下文初始化
