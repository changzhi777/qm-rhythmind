# CLAUDE.md — docs/workflows

> 🧭 [工作空间](../../../CLAUDE.md) > [qm-rhythmind](../../CLAUDE.md) > [docs](../) > **workflows**

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 目录说明

存放数据分析工作流文档，定义从原始数据到最终报告的完整流程。

---

## 文件清单

| 文件 | 说明 | 行数 |
|------|------|------|
| `garmin-data-analysis-workflow.md` | 佳明数据分析工作流 v1.0 — 7 阶段完整流程 | 366 |

---

## 使用场景

执行健康数据分析任务时，参照本工作流按阶段推进，避免遗漏关键步骤。重点关注 **SpO2 分析**（OSA 筛查是最大健康价值点）。

---

## 7 阶段流水线总览

```
① 数据读取 → ② 数据解析 → ③ 初步报告(MD) → ④ 可视化(HTML) → ⑤ 专业报告(MD) → ⑥ 通俗解读(MD) → ⑦ PDF
   10min        15min          15min              20min            15min              10min          5min
```

| 阶段 | 核心任务 | 输入 | 产出 | 耗时 | 工具 |
|------|---------|------|------|------|------|
| ① 数据读取 | 理解 Garmin 目录结构、文件清单统计 | 原始 JSON 目录 | 文件清单、用户档案摘要 | 10min | shell find/cat |
| ② 数据解析 | 提取核心指标、数据质量校验 | 阶段①目录理解 | 结构化指标字典 | 15min | Python json 解析 |
| ③ 初步报告 | 10 章结构化 MD 报告 | 阶段②指标字典 | `*_分析报告.md` | 15min | Markdown |
| ④ 可视化 | 暗色仪表盘 HTML + SVG 内联图表 | 阶段②指标字典 | `*_分析报告.html` | 20min | SVG + CSS Grid |
| ⑤ 专业报告 | 面向教练/医生的 8 项增补内容 | 阶段③+④产出 | `*_健康指导报告.md` | 15min | Markdown |
| ⑥ 通俗解读 | 大白话翻译 + 比喻 + 行动建议 | 阶段⑤专业报告 | `*_通俗解读报告.md/.html` | 10min | Markdown + HTML |
| ⑦ PDF 转换 | 所有 MD/HTML → A4 PDF | 阶段③④⑤⑥产出 | 全部 `*.pdf` 文件 | 5min | Playwright |

### 阶段依赖关系

```
① ──→ ② ──→ ③
              ├──→ ④
              └──→ ⑤ ──→ ⑥
                    └──→ ⑦（所有阶段产出汇总转 PDF）
```

---

## 各阶段输入输出详情

### 阶段 ①：数据读取

| 维度 | 详情 |
|------|------|
| 必做操作 | `find` 扫描目录树、`wc -l` 统计文件数、`python3 -m json.tool` 读取用户档案 |
| 关键校验 | 检查 11 个预期子目录是否齐全 |
| 失败处理 | 目录缺失 → 确认解压完整性；文件为空 → 检查 Garmin Connect 导出范围 |

### 阶段 ②：数据解析

| 维度 | 详情 |
|------|------|
| 必提取字段 | 用户档案(5) + VO2Max 趋势(4 季度点) + 睡眠(7 指标/晚) + 训练负荷(4 指标) + HRV 基线 |
| 数据质量校验 | ① 活动距离 >50km 标记可疑 ② 睡眠 <0.5h 或 >14h 标记异常 ③ VO2Max 趋势跳变检测 |
| 关键代码模板 | SpO2 分析（OSA 筛查核心）、ACWR 计算、VO2Max 趋势提取 |

### 阶段 ③：初步报告（10 章 MD）

| 章节 | 内容 | 格式 |
|------|------|------|
| 1: 用户档案 | 基本生理参数表 | 表格 |
| 2: 核心体能 | VO2Max 趋势 + 耐力/爬坡评分 | 表格 + 分析文字 |
| 3: 赛事预测 | 当前预测 vs PB | 对比表格 |
| 4: 训练负荷 | ACWR 分布 + 训练准备度 | 统计数据 |
| 5: 睡眠分析 | 总体 + 质量分布 + 月度趋势 + 近7晚 | 多级数据 |
| 6: 健康状态 | HRV、静息心率、SpO2、呼吸频率 | 指标列表 |
| 7: 运动总览 | 运动类型统计 + PB + 近期跑步 | 列表 + 表格 |
| 8: 心率区间 | Z1-Z5 表 | 表格 |
| 9: 综合评估 | 优势 + 风险 + 行动建议 | 段落 + 列表 |
| 10: 数据质量 | 异常记录 + 限制说明 | 列表 |

### 阶段 ④：可视化页面（14 模块 HTML）

| 模块 | SVG 元素 | 数据绑定 |
|------|---------|---------|
| 头部信息栏 | — | 用户名 + 日期 |
| 用户档案卡 | — | 基本信息表格 |
| KPI 摘要卡 | — | grid-4: VO2Max/体能年龄/睡眠评分/训练准备度 |
| 赛事预测卡 | — | 表格 + PB 对比进度条 |
| 健康状态卡 | — | 指标 + ✅/⚠️ 标签 |
| VO2Max 趋势图 | `polyline` + `fill` | 季度数据点 |
| 睡眠月度趋势 | `rect` | 月均深睡/REM/浅睡 |
| 睡眠质量分布 | `circle` + `stroke-dasharray` | 评分分档 |
| 近14晚睡眠 | `rect` 分组 | 逐日深睡+REM |
| 心率区间卡 | — | 表格 + 渐变色条 |
| ACWR 分布 | `rect` 横向 | 30天 ACWR 分档 |
| 耐力评分趋势 | `polyline` | 时间序列 |
| AI 建议 | — | 优先级标签 + 文字 |
| 个人记录 | — | 表格 |

### 阶段 ⑤：专业报告（8 项增补）

| # | 增补内容 | 说明 |
|---|---------|------|
| 1 | 执行摘要 | 3 项核心风险 + 积极信号，开篇点题 |
| 2 | 深度解读列 | 每个表格增加"解读"列 |
| 3 | SpO2 临床对照表 | 分级(正常/轻度/中度/重度) + 出现频率 |
| 4 | OSA 症状自查表 | 典型表现 vs 用户数据吻合度 |
| 5 | 风险评估矩阵 | 5 维（睡眠呼吸/不足/体能退化/过度训练/心脏） |
| 6 | 3 阶段行动方案 | 周训练表 + VO2Max 专项 + 80/20 原则 |
| 7 | 监测清单 | 每日/每周/每月指标 + 目标范围 + 行动阈值 |
| 8 | 优先级矩阵 | P0-P3 级行动表 |

### 阶段 ⑥：通俗解读（6 条写作规范）

| 原则 | 示例 |
|------|------|
| 比喻替代术语 | VO2Max → "发动机排量"，耐力评分 → "油箱大小" |
| 三段式解释 | 指标是什么 → 你的情况 → 怎么做 |
| 数据故事化 | 用时间线讲述变化过程 |
| 突出关键发现 | 🚨/⚠️ 标记 + 红色框 |
| 可执行建议 | "每晚10:30上床" 非 "早点睡" |
| 体感化描述 | Z2 → "轻松，能说完整的话"，Z4 → "只能蹦词" |

### 阶段 ⑦：PDF 转换

| 参数 | 值 |
|------|-----|
| 引擎 | Playwright `page.pdf()` |
| 前置 | `python3 -m http.server 8888`（file:// 协议限制） |
| 纸张 | A4 |
| 边距 | 上14 / 下14 / 左12 / 右12 mm |
| 页眉 | `RHYTHMIND 律动 · {标题}` 8px #aaa |
| 页脚 | `第 X / Y 页` 8px #aaa |
| 背景 | `print_background=True` |
| 后置 | `kill $(lsof -ti:8888)` 关闭临时 HTTP 服务 |

---

## 数据陷阱速查表

| # | 陷阱 | 症状 | 原因 | 解决方案 |
|---|------|------|------|---------|
| 1 | 睡眠文件名匹配 | `startswith("sleepData")` 返回空 | 文件名是 `{date}_sleepData.json` 非 `sleepData*.json` | `"sleepData" in filename` |
| 2 | 活动距离累积 | 单次跑步 106km | `summarizedActivitiesExport` 距离是累积值 | 检查 `avgSpeed` < 0.5 m/s → 可疑累积值 |
| 3 | JSON 嵌套层级 | `KeyError` 取不到数据 | 活动是 `[{summarizedActivitiesExport: [...]}]` | `data[0]["summarizedActivitiesExport"]` |
| 4 | 文件编码 BOM | `json.loads` 报错 | 部分文件含 BOM 头 | 先 `.encode()` 再 `json.loads()` |

---

## Garmin 目录 → 分析字段映射

| Garmin 目录 | 关键文件 | 提取字段 | 用途 |
|-------------|---------|---------|------|
| `DI-Connect-User-*` | `user.json` | firstName, lastName, birthDate, gender, height | 用户档案 |
| `DI-Connect-User-*` | `weight.json` | weight, bmi | BMI 计算 |
| `DI-Connect-FitnessAge-*` | `*_userfitnessage.json` | vo2Max, fitnessAge, timestamp | VO2Max 趋势 |
| `DI-Connect-Sleep-*` | `*_sleepData.json` | sleepTime, deepSleep, remSleep, avgSpO2, minSpO2, respiration, sleepScore | 睡眠分析 + OSA 筛查 |
| `DI-Connect-TrainingStatus-*` | `metrics/*_metrics.json` | acwr, acuteLoad, chronicLoad | 训练负荷 |
| `DI-Connect-TrainingReadiness-*` | — | score, timestamp | 训练准备度分布 |
| `DI-Connect-Activities-*` | `activities.json` | summarizedActivitiesExport | 运动统计（⚠️ 距离校验） |
| `DI-Connect-RacePredictions-*` | — | time per distance | 赛事预测 + PB 对比 |
| `DI-Connect-PersonalRecords-*` | — | personalRecords | 个人最佳 |
| `DI-Connect-HeartRateVariability-*` | — | weeklyAvg, hrvStatus | HRV 基线 |

---

## 产出文件清单

| 文件 | 格式 | 面向 | 阶段 | 用途 |
|------|------|------|------|------|
| `*_分析报告.md` | Markdown | 内部参考 | ③ | 数据汇总，全部核心指标 |
| `*_分析报告.html` | HTML | 用户/展示 | ④ | 暗色仪表盘，SVG 图表 |
| `*_分析报告.pdf` | PDF | 用户/存档 | ⑦ | HTML 版本打印 |
| `*_健康指导报告.md` | Markdown | 教练/医生 | ⑤ | 专业深度分析 + 方案 |
| `*_通俗解读报告.md` | Markdown | 用户本人 | ⑥ | 大白话解读 |
| `*_通俗解读报告.html` | HTML | 用户/打印 | ⑥ | 白底打印版 |
| `*_通俗解读报告.pdf` | PDF | 用户/存档 | ⑦ | 白底版打印 |

---

## 质量检查清单

| # | 检查项 | 标准 |
|---|--------|------|
| 1 | 核心数据一致 | 三份报告 VO2Max/体能年龄/PB/SpO2 比例相同 |
| 2 | SpO2 完整 | 含 <90% 夜晚比例、历史最低值、分级分布 |
| 3 | 赛事预测完整 | 当前预测 + PB 对比 + 恢复趋势 |
| 4 | 行动建议可执行 | 按优先级排列，具体到时间线和步骤 |
| 5 | 免责声明 | 报告尾部含数据质量说明和免责声明 |
| 6 | HTML 显示正常 | 浏览器打开无错位、无空白图表 |
| 7 | PDF 格式正确 | 页眉页脚完整，无截断或空白页 |

---

## 快速参考

```bash
# 完整工作流快速启动
python3 -c "from pathlib import Path; ..."  # 阶段①② 数据读取+解析
# → 生成 ③ *_分析报告.md
# → 生成 ④ *_分析报告.html (SVG 内联)
python3 -m http.server 8888 &                # 启动 HTTP 服务
# → 生成 ⑤ *_健康指导报告.md
# → 生成 ⑥ *_通俗解读报告.md / .html
python3 convert_to_pdf.py                   # 阶段⑦ 批量 PDF
kill $(lsof -ti:8888)                       # 关闭 HTTP 服务
```

---

## 关联文档

- [[templates](../templates/CLAUDE.md) — 报告模板字段对照表
- [[knowledge](../knowledge/CLAUDE.md) — 领域知识库（OSA/睡眠/VO2max）可供报告引用

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：新增 7 阶段流水线总览 + 阶段依赖图 + 各阶段输入输出详情 + 数据陷阱速查表 + Garmin 目录→字段映射 + 质量检查清单 + 快速参考
- **2026-05-27** 首次 AI 上下文初始化
