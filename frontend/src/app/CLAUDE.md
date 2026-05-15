[根目录](../../../../CLAUDE.md) > [qm-rhythmind](../) > **frontend**

# frontend 模块 — RHYTHMIND 前端

> **最后更新:** 2026-05-15T14:22:35+08:00

---

## 模块职责

Next.js 16 前端项目，提供仪表盘、数据大屏、AI 健康报告三大页面的 UI 展示，使用 Zustand 做状态管理，ECharts 做图表渲染。

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
| `NEXT_PUBLIC_API_URL` | `http://localhost:8888` | 后端 API 地址 |

---

## 对外接口

### 页面路由

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 重定向 | → `/dashboard` |
| `/dashboard` | 仪表盘 | 健康数据展示、KPI 卡片、趋势图 |
| `/bigscreen` | 数据大屏 | 全屏展示、6 列 KPI 网格、年度跑量 |
| `/report` | AI 健康报告 | Markdown 报告渲染、列表选择 |

### API 调用层 (`src/lib/api.ts`)

```typescript
api.getDashboard()                          // 获取仪表盘数据
api.getReports(limit?)                      // 获取报告列表
api.getReport(id)                           // 获取单个报告详情
api.downloadReport(id): Promise<Blob>       // 下载报告 PDF
api.triggerAnalyze()                        // 触发 AI 分析
api.uploadHealth(data)                      // 上传健康数据
```

---

## 关键依赖与配置

| 依赖 | 版本 | 用途 |
|------|------|------|
| `next` | 16.2.6 | App Router 框架 |
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

- **测试目录**: 未创建
- **ESLint 配置**: `eslint.config.mjs` (next/core-web-vitals + typescript)
- **代码检查**: `npm run lint`

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
| `src/lib/api.ts` | API 调用封装 |
| `src/lib/stores/health-store.ts` | 健康数据状态（含 5 分钟缓存） |
| `src/lib/stores/report-store.ts` | 报告状态（含下载状态） |
| `src/components/charts/line-chart.tsx` | ECharts 折线图组件 |
| `src/components/dashboard/kpi-card.tsx` | KPI 状态卡片 |

---

## 变更记录 (Changelog)

- **2026-05-15** 首次 AI 上下文初始化，生成模块文档与导航面包屑