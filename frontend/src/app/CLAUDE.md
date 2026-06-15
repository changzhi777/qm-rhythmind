[根目录](../../../../CLAUDE.md) > [qm-rhythmind](../) > **frontend**

# frontend 模块 — RHYTHMIND 前端

> **最后更新:** 2026-06-11T13:30:00+08:00

---

## 模块职责

Next.js 16 前端项目，提供用户选择首页、仪表盘、数据大屏、AI 健康报告、Chat 智能助手、文件上传、测试报告、医疗报告、LLM 观测共 9 大页面的 UI 展示，使用 Zustand 做状态管理，ECharts 做图表渲染。

---

## 入口与启动

```bash
npm install
npm run dev   # 开发模式
npm run build # 生产构建
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXT_PUBLIC_API_URL` | `/qm/api` | 后端 API 地址（生产相对路径） |

---

## 对外接口

### 页面路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 用户选择 | 多用户摘要卡片，选择后 `setAuthToken(userId)` 并跳转 `/dashboard` |
| `/dashboard` | 仪表盘 | 健康数据展示、KPI 卡片、4 Tab（含 InfluxDB 时序图）、`useAutoRefresh` |
| `/bigscreen` | 数据大屏 | 全屏展示、6 列 KPI 网格、年度跑量、`useAutoRefresh` |
| `/report` | AI 健康报告 | Markdown 报告渲染、列表选择、PDF 下载 |
| `/chat` | Chat 智能助手 | 多轮对话、文件上传分析、流式响应 |
| `/upload` | 文件上传 | CSV/JSON/PDF/图像/TXT 多模态 AI 分析 |
| `/test-report` | 测试报告 | E2E 报告列表、认证文件下载 |
| `/medical` | 医疗报告 | 5 Tab（综合分析/时间线/用药/化验/健康画像） |
| `/llm-observe` | LLM 观测 | LLM 调用指标、Trace 列表、成本统计、优化建议 |

### API 调用层 (`src/lib/api.ts`)

```typescript
api.getDashboard()                          // 获取仪表盘数据
api.getReports(limit?)                      // 获取报告列表
api.getReport(id)                           // 获取单个报告详情
api.downloadReport(id): Promise<Blob>       // 下载报告 PDF
api.triggerAnalyze()                        // 触发 AI 分析
api.uploadHealth(data)                      // 上传健康数据
api.getUsersSummary()                       // 获取多用户摘要
api.getInfluxTimeSeries(metric, range?, agg?, fn?)  // InfluxDB 时序数据 (2026-06-10 新增)
```

**认证层：** 所有调用走 `fetchWithAuth<T>`，自动注入 `Authorization: Bearer <token>`；401 时清除 token 并跳回 `/`（详见 [lib/CLAUDE.md](../lib/CLAUDE.md)）。

---

## 关键依赖与配置

| 依赖 | 版本 | 用途 |
|------|------|------|
| `next` | 16.2.6 | App Router 框架（静态导出） |
| `react` | 19.2.4 | UI 库 |
| `zustand` | 5.0.13 | 状态管理 |
| `echarts` | 6.0.0 | 图表 |
| `tailwindcss` | 4.x | 样式 |
| `recharts` | 3.8.1 | 备用图表库 |
| `leaflet` | 1.9.4 | 地图（待用） |

---

## 数据模型

### HealthData 键值结构

```typescript
// Profile
'profile.age': number
'profile.bmi': number
'profile.weight_kg': number
'profile.vo2_max': number
'profile.resting_hr': number
'profile.max_hr': number

// Training
'training.metrics': {
  readiness_score: number
  acwr: number
  endurance_score: number
  hill_score: number
}

// Running
'running.summary': {
  total_distance: number
  total_runs: number
  avg_pace_min_per_km: number
}

// Sleep
'sleep.summary': {
  avg_total_hours: number
  deep_pct: number
}

// Activity
'activity_summary.yearly': Record<string, { distance: number; count: number }>
```

---

## 测试与质量

- **E2E 测试**: `tests/e2e_test.py` — 10 轮 × 19 用例 = 190 用例全链路测试 + MD/HTML/PDF 报告（基线：100% 通过）
- **ESLint 配置**: `eslint.config.mjs` (next/core-web-vitals + typescript)
- **代码检查**: `npm run lint`（基线：零错误）
- **Tailwind 迁移**: 7 个页面 inline style 全部迁移到 Tailwind class（2026-06-10 完成）

---

## 常见问题 (FAQ)

**Q: 数据大屏与仪表盘有何区别？**
A: 大屏采用 6 列 KPI 网格、2:1 布局的图表区，并增加了运动轨迹入口（即将推出）。

**Q: 如何添加新的图表类型？**
A: 在 `src/components/charts/` 目录下创建新的 ECharts 封装组件，参考 `line-chart.tsx` 的模式。

**Q: 如何扩展新的健康数据字段？**
A: 1) 在 `src/types/health.ts` 添加类型；2) 在 `health-store.ts` 添加选择器；3) 在 API 层添加对应的数据获取逻辑。

---

## 相关文件清单

| 文件 | 用途 |
|------|------|
| `src/app/globals.css` | 全局样式、主题色 CSS 变量 |
| `src/lib/api.ts` | API 调用封装（`fetchWithAuth<T>` + 401 拦截） |
| `src/lib/stores/health-store.ts` | 健康数据状态（含 5 分钟缓存） |
| `src/lib/stores/report-store.ts` | 报告状态（含下载状态） |
| `src/lib/stores/llm-observe-store.ts` | LLM 观测状态 |
| `src/lib/hooks/use-auto-refresh.ts` | 定时刷新 Hook（2026-06-10 新增） |
| `src/components/charts/line-chart.tsx` | ECharts 折线图组件 |
| `src/components/charts/influx-time-series-chart.tsx` | InfluxDB 时序图组件（2026-06-10 新增） |
| `src/components/dashboard/kpi-card.tsx` | KPI 状态卡片 |
| `src/components/ui/skeleton.tsx` | 加载骨架屏（2026-06-10 新增） |
| `src/components/layout/header.tsx` | 统一 Header（含用户头像/退出登录） |

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：修复页面路由表重复行、补充 `getInfluxTimeSeries` 端点、刷新 ESLint/E2E 基线、补全相关文件清单（含 6/10 新增组件）
- **2026-06-10** 增量更新：仪表盘 4 Tab + InfluxDB 时序图、`<Skeleton />` 组件、`useAutoRefresh` Hook、401 强制跳首页、Tailwind 全量迁移
- **2026-05-27** 增量更新：首页改为用户选择页（多用户摘要卡片）、Header 用户头像+退出登录、V1_BASE + setAuthToken
- **2026-05-26** 增量更新：新增 /medical、/llm-observe 页面，新增 llm-observe-store
- **2026-05-15** 首次 AI 上下文初始化，生成模块文档与导航面包屑
