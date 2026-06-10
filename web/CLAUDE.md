# CLAUDE.md — web/ Vue.js 替代前端

> `[根目录(../CLAUDE.md) > **web**`

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

单文件 Vue.js 3 + ECharts + Three.js 健康仪表盘前端，不依赖 Node.js 构建工具链。通过 CDN 加载依赖，由 FastAPI StaticFiles 或 nginx 直接服务。

---

## 技术方案

- **Vue.js 3** (CDN `vue.global.prod.js`) — Options API + `setup()`
- **ECharts 5** (CDN) — 数据图表（柱状/折线/饼图/仪表盘/雷达）
- **Three.js 0.160** (ESM importmap) — 3D 体素人物头像
- **html2pdf.js 0.10.1** (CDN) — 前端 PDF 导出（html2canvas + jsPDF）
- **marked.js** (CDN) — Markdown 渲染（AI 报告）

---

## 文件结构

```
web/
├── index.html    # 单文件应用（620 行，Vue 3 SFC + 3D + ECharts）
└── style.css     # 暗色主题样式（272 行，CSS 变量）
```

---

## 对外接口

由 `scripts/run_ingestion.py --serve` 在 `localhost:8088` 启动，路由：

| 方法 | 路由 | 用途 |
|------|------|------|
| `GET` | `/` | 仪表盘页面 (`index.html`) |
| `GET` | `/static/*` | CSS 等静态资源 |
| `GET` | `/api/dashboard` | 仪表盘数据（通过 dashboard_router） |
| `GET` | `/api/reports?limit=N` | AI 报告列表 |
| `GET` | `/api/reports/{id}` | 单个报告详情 |
| `POST` | `/api/analyze` | 触发 AI 分析（三阶段 Swarm 流水线） |

### API 数据格式

```typescript
// GET /api/dashboard 返回
{
  data: {
    "profile.gender": string,
    "profile.age": number,
    "profile.height_cm": number,
    "profile.weight_kg": number,
    "profile.bmi": number,
    "profile.vo2_max": number,
    "profile.resting_hr": number,
    "profile.max_hr": number,
    "profile.hr_zones": Record<string, [number, number]>,
    "running.summary": { total_distance, total_runs, avg_pace_min_per_km },
    "sleep.summary": { avg_total_hours, deep_pct, avg_deep_hours, avg_rem_hours, record_days },
    "training.metrics": {
      readiness_score, acwr, acwr_status, endurance_score, endurance_class,
      hill_score, race_predictions: Record<string, number>
    },
    "activity_summary.yearly": Record<string, { distance, count }>,
    "body_metrics.summary": { vo2_max_latest, vo2_max_max }
  }
}

// GET /api/reports 返回
{ reports: [{ id, timestamp, is_current, preview }] }

// GET /api/reports/{id} 返回
{ report: { id, content, model, timestamp } }
```

---

## Vue 组件树与数据流

### 响应式状态 (ref)

| 变量 | 类型 | 初始值 | 说明 |
|------|------|--------|------|
| `view` | `'dashboard' \| 'report'` | `'dashboard'` | 当前视图（单页路由） |
| `data` | `Record<string, any>` | `{}` | 仪表盘全量健康数据 |
| `reports` | `Report[]` | `[]` | 报告列表 |
| `latestReport` | `Report \| null` | `null` | 最新报告（首页摘要用） |
| `selectedReport` | `Report \| null` | `null` | 当前选中报告（详情视图） |
| `analyzing` | `boolean` | `false` | AI 分析中标志 |

### 数据流

```
onMounted
    ↓
fetchDashboard()  ─────────────────────────────┐
    │ fetch /api/dashboard                      │
    │ data.value = json.data                    │
    ↓                                           │
nextTick()                                      │
    ├─ initVoxel()        → Three.js 3D 人物    │
    ├─ renderCharts()                            │
    │   ├─ renderYearlyChart()  → 年度跑量       │
    │   ├─ renderMonthlyChart() → 月度跑量       │
    │   ├─ renderPaceChart()    → 配速分布       │
    │   ├─ renderHRZonesChart() → 心率区间       │
    │   ├─ renderVO2Chart()     → VO2Max 仪表盘  │
    │   └─ renderSleepChart()   → 睡眠饼图       │
    └─ fetchLatestReport()                       │
        └─ → latestReport.value ←───────────────┘
```

### 函数签名

| 函数 | 签名 | 说明 |
|------|------|------|
| `fetchDashboard()` | `async () => void` | 获取仪表盘数据 → 渲染所有图表 + 3D 人物 |
| `fetchLatestReport()` | `async () => void` | 获取最新报告摘要（仪表盘底部预览） |
| `loadReports()` | `async () => void` | 切换到报告视图，加载报告列表 |
| `selectReport(r)` | `(r: Report) => void` | 点击报告卡片 → 请求详情 → 渲染 Markdown |
| `triggerAnalyze()` | `async () => void` | POST → 重新分析 → 刷新仪表盘数据 |
| `initVoxel()` | `() => void` | 获取 canvas → 调用 `window.initVoxelHuman(canvas, data)` |
| `renderCharts()` | `() => void` | 统一调度 6 个图表渲染函数 |
| `racePredictions()` | `() => Record<string, number>` | 从 `data['training.metrics']` 提取赛事预测 |
| `formatRaceTime(seconds)` | `(seconds: number) => string` | `3661` → `"1:01:01"` |
| `formatTime(ts)` | `(ts: string) => string` | ISO → `"YYYY-MM-DD HH:mm:ss"` |
| `renderMarkdown(text)` | `(text: string) => string` | marked.parse() |
| `downloadPDF()` | `() => void` | html2pdf 前端导出 A4 PDF |

---

## ECharts 图表详细规格

### 1. 年度跑量 (`chart-yearly`)

| 属性 | 值 |
|------|-----|
| 类型 | 柱状图 + 折线图（双 Y 轴） |
| 数据源 | `data['activity_summary.yearly']` |
| X 轴 | 年份（排序） |
| 左 Y 轴 | 跑量(km) = `distance / 100000`（柱状 `#4fc3f7`） |
| 右 Y 轴 | 活动次数（折线 `#81c784`） |

### 2. 月度跑量 (`chart-monthly`)

| 属性 | 值 |
|------|-----|
| 类型 | 柱状图 |
| 数据源 | 年度数据均分到月 + 随机抖动（无真实月度数据时的兜底） |
| X 轴 | `YYYY-MM`，标签旋转 45° |
| 缩放 | dataZoom inside，起始 70% |

### 3. 配速分布 (`chart-pace`)

| 属性 | 值 |
|------|-----|
| 类型 | 柱状图 + markLine |
| 数据 | 7 档配速估分布（4:00~7:00+） |
| 配色 | 红→橙→黄→绿→蓝→靛→灰 |
| markLine | 标记平均配速位置 |

### 4. 心率区间 (`chart-hr`)

| 属性 | 值 |
|------|-----|
| 类型 | 渐变柱状图（Z1~Z5） |
| 数据源 | `data['profile.hr_zones']` |
| Y 轴 | bpm 范围宽度 |
| 配色 | 绿 `#66bb6a` → 红 `#ef5350` → 深红 `#ad1457` 渐变 |

### 5. VO2Max 仪表盘 (`chart-vo2`)

| 属性 | 值 |
|------|-----|
| 类型 | ECharts gauge |
| 数据源 | `data['body_metrics.summary']` |
| 量程 | 20-70 ml/kg/min |
| 角度 | 200° ~ -20°（240° 弧） |
| 颜色分区 | 红(20-30) → 橙(30-40) → 绿(40-50) → 蓝(50-70) |
| 峰值标注 | graphic text 显示历史峰值 |

### 6. 睡眠饼图 (`chart-sleep`)

| 属性 | 值 |
|------|-----|
| 类型 | 环形饼图（radius: 40%-70%） |
| 数据 | 深睡(`#7e57c2`) + REM(`#5c6bc0`) + 浅睡(`#42a5f5`) |
| 渲染 | 延迟 100ms（等待 DOM） |

---

## Three.js 3D 体素人物

### 管线

```
profile.vo2_max
    ↓
HSL 色彩映射: hue = 0.55 + (vo2_max - 40) * 0.01
    ↓
体素点生成 (11 个身体部位, ~1500 个点)
    ↓
颜色渐变: 脚部 → 头部 bodyColor → glowColor
    ↓
OrbitControls: 旋转/缩放（不平移）
    ↓
requestAnimationFrame: Y 轴自动旋转 0.005 rad/frame
```

### 身体部位点分布

| 部位 | 点数量 | 形状 |
|------|--------|------|
| 头部 | 200 | 球体 (r=0.12) |
| 颈部 | 30 | 小圆柱 |
| 躯干 | ~400 | 锥形圆柱（胸 r=0.18 → 腰 r=0.14） |
| 肩部 | 120 | 双球体 |
| 上臂 | 120 | 双圆柱 |
| 前臂 | 100 | 双圆柱（细） |
| 大腿 | 200 | 双圆柱（粗） |
| 小腿 | 160 | 双圆柱（中） |
| 脚部 | 80 | 双椭球 |
| 环境光晕 | 500 | 球壳散布 |

---

## PDF 导出

| 步骤 | 实现 |
|------|------|
| 1. 创建临时 div | `className='pdf-export'`，渲染 Markdown + 标题 + 元信息 |
| 2. html2canvas | `scale: 2`（高清），`useCORS: true` |
| 3. jsPDF | A4，portrait，文件名 `RHYTHMIND-AI报告-{时间戳}.pdf` |
| 4. 清理 | `.then(() => tmp.remove())` |

---

## 设计系统

暗色主题（GitHub Dark 风格），CSS 变量：

```css
--bg: #0d1117;       --card: #161b22;
--border: #30363d;   --text: #c9d1d9;
--accent: #58a6ff;   --success: #3fb950;
--warning: #d29922;  --danger: #f85149;
```

---

## 与 Next.js 前端的关系

| 维度 | `web/` (替代前端) | `frontend/` (主力前端) |
|------|-------------------|----------------------|
| 框架 | Vue 3 CDN（无构建） | Next.js 16 + React 19 |
| 部署 | `run_ingestion.py --serve` | `next build` → static export → nginx |
| 图表 | ECharts (CDN) | ECharts + Recharts (npm) |
| 3D | Three.js 体素人物 | — |
| PDF | html2pdf.js (前端) | 后端生成 |
| 状态 | Vue ref (组件内) | Zustand stores |
| 路由 | 单页 `view` 切换 | App Router 多页面 |
| 用户选择 | — | 首页用户卡片 + 多用户隔离 |
| 医疗/LLM 观测 | — | 完整功能页面 |

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：新增 Vue 组件树、数据流图、ECharts 6 图详细规格、Three.js 体素管线、PDF 导出步骤、API 返回格式、Next.js 对比表
- **2026-05-18** 首次 AI 上下文初始化
