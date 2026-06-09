# 佳明手表健康数据报告模板

> **模板版本:** v1.0
> **创建日期:** 2026-05-27
> **适用场景:** Garmin Connect 完整数据导出的健康分析报告
> **报告类型:** 通俗解读版（面向用户）/ 专业分析版（面向教练/医生）

---

## 模板说明

本模板基于 2026-05-27 佳明数据分析实践总结，包含三种报告格式：
- **通俗解读报告：** 面向用户本人，大白话解释，重点突出行动建议
- **专业分析报告：** 面向教练/医生，专业术语，数据完整
- **可视化页面（HTML）：** 暗色主题仪表盘，SVG 内联图表，支持转 PDF

三份报告各有侧重，核心数据保持一致。

---

## 一、报告头部元信息

```markdown
# 佳明手表健康数据[通俗解读/综合分析]报告

> **[解读对象/用户]：** [姓名]（[性别]，[年龄]岁，[身高]cm，[体重]kg）
> **数据范围：** [起始年月] — [结束年月]（共[X]年[Y]个月）
> **报告日期：** YYYY-MM-DD
> **数据来源：** Garmin Connect 完整导出（[X]晚睡眠、[Y]次运动记录、[Z]天训练负荷）
> **生成平台：** RHYTHMIND 律动 AI 健康管理平台
```

**必填字段：** 用户姓名、性别、年龄、身高、体重、数据时间跨度、报告日期
**选填字段：** 运动次数、睡眠晚数、训练负荷天数（从数据中自动统计）

---

## 二、报告章节结构

### 通俗解读版（面向用户，10章）

| 章节号 | 章节标题 | 核心内容 | 写作要求 |
|--------|---------|---------|---------|
| 前言 | 写在前面 | 报告定位和使用说明 | 2-3句话，说明报告会告诉用户什么 |
| 第一章 | 身体基本情况 | BMI、静息心率、运动经历 | 用比喻解释每个指标，列出PB成绩 |
| 第二章 | 体能评估 | VO2Max趋势、耐力评分、爬坡能力 | 用"发动机排量""油箱"等比喻，按时间线讲故事 |
| 第三章 | 赛事预测 | 当前预测成绩、与PB对比、趋势变化 | 表格对比，突出差距和恢复趋势 |
| 第四章 | 训练规律性 | ACWR分布、训练准备度 | 用生活场景类比，指出具体问题 |
| 第五章 | 睡眠分析（最重要）| 时长/质量/结构/血氧 | 这是核心章节，SpO2分析是重中之重 |
| 第六章 | 白天健康状态 | HRV、静息心率、白天血氧 | 简洁确认白天指标正常，突出夜间问题 |
| 第七章 | 心率区间 | Z1-Z5心率范围和训练建议 | 用"聊天测试"描述每个区间的体感 |
| 第八章 | 总结与行动 | 三件大事 + 分步行动建议 | 用优先级标签，给出具体可执行的时间表 |
| 第九章 | 饮食恢复建议 | 蛋白质/碳水/铁/酒精/补给 | 给出具体食物量和时间点 |
| 第十章 | 一句话总结 | 用比喻总结核心信息 | 一段话，用"跑车"或类似比喻收尾 |

### 专业分析版（面向教练/医生，12章）

| 章节号 | 章节标题 | 核心内容 | 数据深度 |
|--------|---------|---------|---------|
| 一 | 执行摘要 | 3项核心风险 + 积极信号 | 精确数值 + 百分比 |
| 二 | 用户档案 | 完整生理参数表 | 含参考范围和评价列 |
| 三 | 核心体能 | VO2Max季度趋势、耐力评分、爬坡评分 | 含参照标准（同龄排名） |
| 四 | 赛事预测 | 当前预测、PB对比、6个月轨迹 | 含恢复所需时间估算 |
| 五 | 训练负荷 | ACWR状态分布、训练准备度统计 | 量化分布（天数/百分比） |
| 六 | 睡眠分析 | 时长/质量/结构/SpO2/REM | **SpO2<90%夜晚占比是关键指标** |
| 七 | 健康监测 | HRV、静息心率、血氧、呼吸频率 | 含基线范围对比 |
| 八 | 风险评估 | 5维风险矩阵（高/中/低） | 每维度附依据 |
| 九 | 分阶段方案 | 3阶段行动计划（含周训练表） | 具体到每天练什么、心率多少 |
| 十 | 监测清单 | 每日/每周/每月监测指标 | 含目标范围和行动阈值 |
| 十一 | 饮食恢复 | 营养要点、恢复优化 | 含具体克数/时间点 |
| 十二 | 优先级矩阵 | P0-P3级行动清单 | 含预期收益和时间线 |

---

## 三、核心数据项与来源

### 3.1 Garmin 数据文件对应表

| 数据类别 | 文件路径模式 | 关键字段 | 注意事项 |
|---------|-------------|---------|---------|
| 用户档案 | `DI_CONNECT/DI-Connect-User-*/user.json` | `firstName`, `lastName`, `birthDate`, `gender` | 姓名可能在多个位置 |
| 身体指标 | `DI_CONNECT/DI-Connect-User-*/weight.json` | `date`, `weight`, `bmi` | 取最新有效值 |
| Fitness Age | `DI_CONNECT/DI-Connect-FitnessAge-*/` | `fitnessAge`, `vo2Max`, `timestamp` | 按时间排序取趋势 |
| 睡眠数据 | `DI_CONNECT/DI-Connect-Sleep-*/sleepData*.json` | `sleepTimeSeconds`, `deepSleepSeconds`, `remSleepSeconds`, `sleepScores` | 文件名用 `in` 匹配而非 `startswith` |
| 睡眠SpO2 | `DI_CONNECT/DI-Connect-Sleep-*/sleepData*.json` | `avgSpO2`, `minSpO2`, `avgRespiration` | **59%<90%是OSA筛查关键** |
| 训练负荷 | `DI_CONNECT/DI-Connect-TrainingStatus-*/metrics/` | `acwr`, `acuteLoad`, `chronicLoad` | 取最近30-60天 |
| 训练准备度 | `DI_CONNECT/DI-Connect-TrainingReadiness-*/` | `score`, `timestamp` | 统计高/低天数 |
| 活动记录 | `DI_CONNECT/DI-Connect-Activities-*/activities.json` | `summarizedActivitiesExport` | **距离/时长可能是累积值，慎用** |
| 赛事预测 | `DI_CONNECT/DI-Connect-RacePredictions-*/` | `time`, `distance` | 按时间排序取趋势 |
| 个人最佳 | `DI_CONNECT/DI-Connect-PersonalRecords-*/` | `personalRecords` | 取各距离最佳 |
| HRV | `DI_CONNECT/DI-Connect-HeartRateVariability-*/` | `hrvStatus`, `weeklyAvg` | 取最新基线范围 |

### 3.2 关键计算指标

| 指标 | 计算方式 | 正常范围 | 预警阈值 |
|------|---------|---------|---------|
| BMI | weight / (height_m)² | 18.5-24.9 | >24.9 偏胖 |
| 体能年龄 | 手表VO2Max推算 | ≤实际年龄为优 | >实际年龄+5需关注 |
| ACWR | 急性负荷(7天) / 慢性负荷(28天) | 0.8-1.3 | <0.8 训练不足，>1.5 受伤风险 |
| SpO2夜间 | 手表直接采集 | ≥95% | <90%为低氧事件 |
| REM比例 | remSleepSeconds / sleepTimeSeconds | 20-25% | <15%需关注 |
| 训练准备度 | 手表综合评分 | ≥70 | <40 不建议高强度训练 |

### 3.3 SpO2 分析模板（OSA 筛查核心）

```python
# SpO2 低氧事件统计
total_nights = len(sleep_records)
hypoxic_nights = sum(1 for r in sleep_records if r['minSpO2'] < 90)
hypoxic_ratio = hypoxic_nights / total_nights

# 分级统计
normal = sum(1 for r in sleep_records if r['avgSpO2'] >= 95)
mild = sum(1 for r in sleep_records if 90 <= r['avgSpO2'] < 95)
moderate = sum(1 for r in sleep_records if 85 <= r['avgSpO2'] < 90)
severe = sum(1 for r in sleep_records if r['avgSpO2'] < 85)

# OSA 高度怀疑标准
if hypoxic_ratio > 0.3:  # >30% 夜晚 SpO2<90%
    osa_risk = "HIGH"
```

---

## 四、可视化页面（HTML）模板规范

### 4.1 技术要求

| 项目 | 规范 |
|------|------|
| 主题 | 暗色主题（#0d1117 背景）或白底打印版 |
| 图表 | SVG 内联，无外部依赖 |
| 字体 | system-ui 无衬线字体栈 |
| 布局 | CSS Grid 响应式，最大宽度 1100px |
| 打印 | `@page { size: A4; }` + `@media print` 适配 |
| PDF | Playwright `page.pdf()` 生成，A4 格式 |

### 4.2 图表清单

| 图表 | 类型 | 数据来源 | SVG实现 |
|------|------|---------|---------|
| VO2Max 趋势 | 折线图 + 面积填充 | Fitness Age 历史数据 | polyline + fill |
| 睡眠月度趋势 | 柱状图 | 睡眠数据按月聚合 | rect |
| 睡眠质量分布 | 饼图 | 评分分档统计 | circle + stroke-dasharray |
| 最近14晚睡眠 | 分组柱状图 | 最近14天逐日数据 | rect 组 |
| ACWR 分布 | 横向条形图 | 30天ACWR分档 | rect |
| 耐力评分趋势 | 折线图 | Endurance Score 历史 | polyline |
| 训练准备度 | 散点/面积图 | Training Readiness | polyline + fill |

### 4.3 HTML → PDF 转换脚本

```python
from playwright.sync_api import sync_playwright

def html_to_pdf(html_path: str, pdf_path: str, title: str = "健康报告"):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{html_path}", wait_until="networkidle")
        page.pdf(
            path=pdf_path,
            format="A4",
            margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
            print_background=True,
            display_header_footer=True,
            header_template=f'<div style="font-size:8px;color:#aaa;text-align:center;margin-top:4px;">RHYTHMIND 律动 · {title}</div>',
            footer_template='<div style="font-size:8px;color:#aaa;text-align:center;margin-bottom:4px;">第 <span class="pageNumber"></span> / <span class="totalPages"></span> 页</div>'
        )
        browser.close()
```

---

## 五、报告尾部（统一格式）

```markdown
---

*本报告基于佳明手表自动采集数据生成，仅供健康管理参考，不构成医学诊断。如有持续不适，请及时就医。*

*湖南青沐生命科技有限公司*
*RHYTHMIND 律动 AI 健康管理平台*
*YYYY年M月D日*
```

---

## 六、数据质量注意事项（报告必附）

每份报告末尾需包含数据质量说明：

1. **活动距离异常：** Garmin 活动文件中部分距离/时长为累积值，非单次活动数据
2. **睡眠可能偏低：** 手表不合并午睡/分段睡眠，实际睡眠可能长于记录
3. **SpO2 准确性：** 腕式光电传感器精度有限，低值需医疗设备确认
4. **体重/体脂：** 如无智能体脂秤数据，BMI 依赖用户手动输入
