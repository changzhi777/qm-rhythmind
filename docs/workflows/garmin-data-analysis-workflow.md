# 佳明数据分析工作流

> **工作流版本:** v1.0
> **创建日期:** 2026-05-27
> **基于实践:** 佳明数据20260526 完整分析（张晨，3.5年数据）
> **预计耗时:** 60-90 分钟（含 PDF 生成）
> **前置依赖:** Python 3.12+, Playwright (`pip install playwright` + `playwright install chromium`)

---

## 工作流概览

```
原始数据 → ①数据读取 → ②数据解析 → ③初步分析报告(MD) → ④可视化页面(HTML) → ⑤专业分析报告(MD) → ⑥通俗解读报告(MD) → ⑦转PDF
```

| 阶段 | 产出 | 耗时估计 |
|------|------|---------|
| ① 数据读取与探索 | 目录结构理解、文件清单 | 10min |
| ② 数据解析 | 核心指标提取、异常识别 | 15min |
| ③ 初步分析报告 | `*_分析报告.md` | 15min |
| ④ 可视化页面 | `*_分析报告.html`（暗色仪表盘） | 20min |
| ⑤ 专业分析报告 | `*_健康指导报告.md` | 15min |
| ⑥ 通俗解读报告 | `*_通俗解读报告.md` | 10min |
| ⑦ PDF 转换 | `*.pdf`（所有MD/HTML版本） | 5min |

---

## 阶段 ①：数据读取与探索

### 目标
理解 Garmin Connect 数据导出的目录结构和文件组织方式。

### Garmin 导出目录结构

```
佳明数据YYYYMMDD/
├── DI_CONNECT/
│   ├── DI-Connect-User-{ID}/              # 用户基本信息
│   │   ├── user.json                      # 姓名、生日、性别、身高
│   │   └── weight.json                    # 体重、BMI 历史
│   ├── DI-Connect-FitnessAge-{ID}/        # 体能年龄 & VO2Max
│   │   └── {date1}_{date2}_{ID}_userfitnessage.json
│   ├── DI-Connect-Sleep-{ID}/             # 睡眠数据
│   │   └── {date1}_{date2}_{ID}_sleepData.json
│   ├── DI-Connect-TrainingStatus-{ID}/    # 训练负荷 & ACWR
│   │   └── metrics/
│   │       └── {date1}_{date2}_{ID}_metrics.json
│   ├── DI-Connect-TrainingReadiness-{ID}/ # 训练准备度
│   ├── DI-Connect-Activities-{ID}/        # 运动活动记录
│   │   └── activities.json                # ⚠️ 距离可能是累积值
│   ├── DI-Connect-RacePredictions-{ID}/   # 赛事预测
│   ├── DI-Connect-PersonalRecords-{ID}/   # 个人最佳
│   └── DI-Connect-HeartRateVariability-{ID}/ # HRV
└── {其他目录}
```

### 操作步骤

```bash
# 1. 查看顶层目录结构
find 佳明数据YYYYMMDD/ -maxdepth 3 -type d | head -30

# 2. 统计文件数量和类型
find 佳明数据YYYYMMDD/ -name "*.json" | wc -l
find 佳明数据YYYYMMDD/ -name "*.json" -exec basename {} \; | sed 's/.*_//' | sort | uniq -c | sort -rn

# 3. 读取用户档案
cat 佳明数据YYYYMMDD/DI_CONNECT/DI-Connect-User-*/user.json | python3 -m json.tool | head -50
```

### 常见陷阱

| 陷阱 | 说明 | 解决方案 |
|------|------|---------|
| 睡眠文件名匹配 | 文件名如 `2026-02-17_2026-05-28_11032831_sleepData.json`，`startswith("sleepData")` 匹配不到 | 用 `"sleepData" in filename` |
| 活动距离累积 | `activities.json` 中 `summarizedActivitiesExport` 的 distance 字段可能是累积值（106km、1001km等） | 检查 `avgSpeed`（0.2-0.4 m/s = 累积值），改用 Fitness Age/Metrics 数据 |
| JSON 嵌套 | 活动数据是 `[{"summarizedActivitiesExport": [...]}]` 而非直接数组 | 先取 `[0]["summarizedActivitiesExport"]` |
| 编码问题 | 部分文件可能有 BOM | `json.loads(content.encode('utf-8'))` |

---

## 阶段 ②：数据解析

### 目标
从 JSON 文件中提取所有关键指标，形成结构化数据。

### 必须提取的数据项

```python
# === 用户档案 ===
# user.json → firstName, lastName, birthDate, gender
# weight.json → 最新 weight, height, bmi

# === VO2Max 趋势 ===
# FitnessAge 文件 → [{"fitnessAgeUpdates": [{"vo2Max": ..., "fitnessAge": ..., "timestamp": ...}]}]
# 按时间排序，提取季度/月度趋势

# === 睡眠数据 ===
# sleepData 文件 → 每晚记录：
# - sleepTimeSeconds, deepSleepSeconds, remSleepSeconds
# - sleepScores.overallScore.value (睡眠评分)
# - avgSpO2, minSpO2 (血氧——最重要的健康指标)
# - avgRespiration (呼吸频率)

# === 训练负荷 ===
# metrics 文件 →
# - acwr (急慢性负荷比)
# - acuteLoad, chronicLoad
# 按最近30-60天统计分布

# === 训练准备度 ===
# TrainingReadiness 文件 → score, timestamp
# 统计平均值、高准备度天数(≥70)、低准备度天数(<40)

# === 赛事预测 ===
# RacePredictions 文件 → 按距离和时间排序
# 提取最新预测和历史趋势

# === 个人最佳 ===
# PersonalRecords 文件 → 各距离最佳成绩

# === HRV 基线 ===
# HeartRateVariability 文件 → 最新基线范围
```

### SpO2 分析（OSA 筛查核心）

```python
# 这是整个分析中最关键的健康指标
total_nights = len(sleep_records)
nights_below_90 = sum(1 for s in sleep_records if s['minSpO2'] < 90)
ratio = nights_below_90 / total_nights

# 输出：
# - SpO2<90% 的夜晚数/总夜晚数 (百分比)
# - 历史最低 SpO2
# - 平均睡眠 SpO2
# - 分级分布 (正常/轻度/中度/重度低氧)
```

### 数据质量校验

```python
# 1. 活动距离合理性检查
for act in activities:
    if act.get('distance', 0) > 50000:  # >50km for a single "run"
        print(f"⚠️ 可疑距离: {act['distance']}m, avgSpeed={act.get('avgSpeed')}")

# 2. 睡眠时长合理性
for s in sleep_records:
    hours = s['sleepTimeSeconds'] / 3600
    if hours > 14 or hours < 0.5:
        print(f"⚠️ 可疑睡眠时长: {hours}h")

# 3. VO2Max 趋势连续性检查
# 确保没有异常跳变（如从50突然到30）
```

---

## 阶段 ③：初步分析报告（MD）

### 目标
生成结构化的 Markdown 分析报告，包含所有关键数据和分析结论。

### 输出文件
`佳明数据YYYYMMDD_分析报告.md`

### 章节结构（10章）

1. **用户档案** — 基本生理参数表格
2. **核心体能指标** — VO2Max趋势表 + 耐力评分 + 爬坡评分
3. **赛事预测** — 当前预测 + PB对比
4. **训练负荷** — ACWR分布 + 训练准备度
5. **睡眠分析** — 总体数据 + 质量分布 + 月度趋势 + 最近7晚
6. **健康状态** — HRV、静息心率、血氧、呼吸频率
7. **运动活动总览** — 运动类型统计 + PB + 最近跑步记录
8. **心率区间** — Z1-Z5训练区间表
9. **综合健康评估** — 优势 + 风险 + 行动建议
10. **数据质量说明** — 异常记录和限制

### 关键格式规范

```markdown
### 2.1 VO2 Max 最大摄氧量

| 时间点 | VO2Max | 体能年龄 | 趋势 |
|--------|--------|---------|------|
| ... | **53.0** | **24.6岁** | ↑ 最佳状态 |

**分析:** [1-3句数据解读，含百分比变化和参照标准]
```

---

## 阶段 ④：可视化页面（HTML）

### 目标
生成独立的 HTML 文件，暗色主题仪表盘风格，SVG 内联图表，支持浏览器查看和 PDF 导出。

### 输出文件
`佳明数据YYYYMMDD_分析报告.html`

### 技术规范

```
- 单文件，无外部依赖
- 暗色主题：background #0d1117, card #161b22, accent #00C9A7
- SVG 图表内联（polyline, rect, circle + stroke-dasharray）
- CSS Grid 布局：grid-2, grid-3, grid-4
- @page A4 打印适配
- JavaScript 数据对象内嵌
```

### 页面模块清单

| 模块 | 实现方式 |
|------|---------|
| 头部信息栏 | Logo + 用户名 + 日期 |
| 用户档案卡 | 头像占位 + 基本信息表格 |
| KPI 摘要卡 | grid-4 四列：VO2Max / 体能年龄 / 睡眠评分 / 训练准备度 |
| 赛事预测卡 | 表格 + PB对比进度条 |
| 健康状态卡 | 指标列表 + 状态标签（✅/⚠️） |
| VO2Max 趋势图 | SVG 折线图 + 面积填充 |
| 睡眠月度趋势 | SVG 柱状图 |
| 睡眠质量分布 | SVG 环形图 |
| 最近14晚睡眠 | SVG 分组柱状图 |
| 心率区间卡 | 表格 + 渐变色条 |
| ACWR 分布 | SVG 横向条形图 |
| 耐力评分趋势 | SVG 折线图 |
| AI 建议 | 优先级标签 + 文字列表 |
| 个人记录 | 表格 |

### SVG 图表模板

```javascript
// 折线图示例（VO2Max趋势）
const data = [
  {x: "2022-Q4", y: 46.6}, {x: "2023-Q2", y: 50.7},
  {x: "2024-Q2", y: 53.0}, {x: "2026-Q2", y: 49.6}
];
const chartW = 700, chartH = 200, pad = 40;
// polyline points 计算 + SVG 输出
```

### 注意事项

- **Playwright file:// 协议限制：** 需启动本地 HTTP 服务器 `python3 -m http.server 8888`
- **中文字体：** 使用系统字体栈，不依赖外部字体文件
- **PDF 生成：** 使用 Playwright `page.pdf()`，A4 格式，含页眉页脚

---

## 阶段 ⑤：专业分析报告（MD）

### 目标
生成面向教练/医生的专业版深度分析报告，含临床对照和分阶段方案。

### 输出文件
`佳明数据YYYYMMDD_健康指导报告.md`

### 核心增补内容（相比初步报告）

1. **执行摘要：** 3项核心风险 + 积极信号，开篇点题
2. **深度解读列：** 每个表格增加"解读"列
3. **SpO2 临床对照表：** 分级（正常/轻度/中度/重度）+ 出现频率
4. **OSA 症状自查表：** 典型表现 vs 用户数据吻合度
5. **风险评估矩阵：** 5维（睡眠呼吸/睡眠不足/体能退化/过度训练/心脏健康）
6. **3阶段行动方案：** 含具体周训练表、VO2Max专项训练、80/20原则
7. **监测清单：** 每日/每周/每月指标 + 目标范围 + 行动阈值
8. **优先级矩阵：** P0-P3级表格

---

## 阶段 ⑥：通俗解读报告（MD + HTML）

### 目标
将专业报告翻译成大白话，面向用户本人，重点是让用户"看得懂、知道怎么做"。

### 输出文件
- `佳明数据YYYYMMDD_通俗解读报告.md`
- `佳明数据YYYYMMDD_通俗解读报告.html`（白底打印版，可选）

### 写作规范

| 原则 | 做法 | 示例 |
|------|------|------|
| 比喻替代术语 | 每个专业术语配一个生活比喻 | VO2Max → "发动机排量"，耐力评分 → "油箱大小" |
| 三段式解释 | 指标是什么 → 你的情况 → 怎么做 | "BMI是什么→你24.9正常→别再涨了" |
| 数据故事化 | 用时间线讲述变化过程 | "从12月到3月，你的体能像过山车一样..." |
| 突出关键发现 | 用🚨/⚠️标记和红色框突出 | "这是整份报告最重要的内容" |
| 可执行建议 | 具体到时间、数量、做法 | "每晚10:30上床" 而非 "早点睡" |
| 类比体感描述 | 用"能聊天/说不出话"描述心率区间 | Z2 "轻松，能说完整的话" |

---

## 阶段 ⑦：PDF 转换

### 目标
将 HTML 报告转为高质量 PDF，支持打印和分发。

### 转换命令

```bash
# 安装依赖（首次）
pip3 install playwright
python3 -m playwright install chromium

# 转换脚本
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('http://127.0.0.1:8888/报告文件.html', wait_until='networkidle')
    page.pdf(
        path='输出.pdf',
        format='A4',
        margin={'top': '14mm', 'bottom': '14mm', 'left': '12mm', 'right': '12mm'},
        print_background=True,
        display_header_footer=True,
        header_template='<div style=\"font-size:8px;color:#aaa;text-align:center;margin-top:4px;\">RHYTHMIND 律动 · 报告标题</div>',
        footer_template='<div style=\"font-size:8px;color:#aaa;text-align:center;margin-bottom:4px;\">第 <span class=\"pageNumber\"></span> / <span class=\"totalPages\"></span> 页</div>'
    )
    browser.close()
"
```

### 注意事项

- HTML 文件需通过 HTTP 服务器访问（file:// 协议 Playwright 有安全限制）
- `python3 -m http.server 8888` 启动临时服务器，完成后 `kill $(lsof -ti:8888)` 关闭
- `print_background=True` 确保暗色主题背景不被忽略
- 白底打印版 HTML 更适合纸质输出

---

## 产出文件清单

分析完成后应产出以下文件：

| 文件 | 格式 | 面向 | 说明 |
|------|------|------|------|
| `佳明数据YYYYMMDD_分析报告.md` | Markdown | 内部参考 | 数据汇总，所有核心指标 |
| `佳明数据YYYYMMDD_分析报告.html` | HTML | 用户/展示 | 暗色仪表盘，SVG图表 |
| `佳明数据YYYYMMDD_分析报告.pdf` | PDF | 用户/存档 | HTML版本打印 |
| `佳明数据YYYYMMDD_健康指导报告.md` | Markdown | 教练/医生 | 专业深度分析+行动方案 |
| `佳明数据YYYYMMDD_通俗解读报告.md` | Markdown | 用户本人 | 大白话解读+行动建议 |
| `佳明数据YYYYMMDD_通俗解读报告.html` | HTML | 用户/打印 | 白底打印版 |
| `佳明数据YYYYMMDD_通俗解读报告.pdf` | PDF | 用户/存档 | 白底版打印 |

---

## 质量检查清单

报告生成后，逐项确认：

- [ ] 三份报告核心数据一致（VO2Max、体能年龄、PB、SpO2比例）
- [ ] SpO2 分析包含：低于90%夜晚比例、历史最低值、分级分布
- [ ] 赛事预测包含：当前预测、PB对比、恢复趋势
- [ ] 行动建议按优先级排列，给出具体时间线和执行步骤
- [ ] 报告尾部包含数据质量说明和免责声明
- [ ] HTML 页面在浏览器中正常显示，图表无错位
- [ ] PDF 页眉页脚正确，无截断或空白页
