[根目录](../../../../CLAUDE.md) > [qm-rhythmind](../) > **frontend**

# CLAUDE.md — RHYTHMIND 律动前端

> **项目版本:** 0.2.0
> **最后扫描:** 2026-06-10T16:53:15+08:00
> **语言:** TypeScript
> **框架:** Next.js 16 (App Router) + React 19
> **包管理:** npm

---

## 变更记录 (Changelog)

- **2026-06-10 (本次)** 前端核心补全：新增 InfluxDB 时序图表（仪表盘 4 Tab）、`<Skeleton />` 通用组件、`useAutoRefresh` Hook、401 强制跳首页、版本号同步 v0.2.0、Header 鼠标悬浮迁移到 CSS class、移除未用 recharts 依赖、提取 yearlyToChart 到 utils.ts
- **2026-05-27** 增量更新：首页改为用户选择页（多用户摘要卡片）、Header 用户头像+退出登录、新增 V1_BASE + setAuthToken、医疗导航
- **2026-05-26** 增量更新：新增 /medical 医疗报告页面（5 Tab）、/llm-observe LLM 观测页面、llm-observe-store.ts 状态管理
- **2026-05-20** 增量更新：Chat 助手页面上线（303行，多轮对话+文件上传）、Upload 文件上传页面上线（172行，CSV/JSON/PDF/图像/TXT）、API_BASE/getAuthToken 统一到 api.ts
- **2026-05-18** 增量更新：规划 Chat 助手页面、文件上传分析页面、返回导航按钮；新增测试报告页面、Header mounted 修复、认证下载
- **2026-05-18** 增量更新：新增测试模块、共享布局组件、工具函数、e2e 报告规范；重构 LineChart（面积图+空数据修复）；报告生成规范（MD+HTML内联SVG→A4 PDF）
- **2026-05-18** 增量更新：新增 leaflet/recharts 依赖、静态导出部署方案、API 前缀 `/qm/api`
- **2026-05-15** 首次 AI 上下文初始化，生成模块结构图与导航面包屑

---

## 项目愿景

RHYTHMIND 律动前端是 Next.js 16 多智能体健康管理平台的数据展示层，采用扁平化 UI 设计风格，主题色为青沐生命青绿色（#00C9A7）。支持用户选择首页、仪表盘、数据大屏、AI 健康报告、Chat 智能助手、文件上传分析、医疗报告、LLM 观测八大核心页面。

---

## 架构总览

### 项目结构图

```mermaid
graph LR
    subgraph "页面 (App Router)"
        HOME[/ 首页]
        DASH[/dashboard 仪表盘]
        BIG[/bigscreen 大屏]
        RPT[/report AI报告]
        CHAT[/chat Chat助手]
        UPLOAD[/upload 文件上传]
        TEST[/test-report 测试报告]
        MED[/medical 医疗报告]
        LLMOBS[/llm-observe LLM观测]
    end

    subgraph "共享组件"
        HEADER[Header 导航栏]
        LINECHART[LineChart 图表]
        KPICARD[KpiCard KPI卡片]
        TOAST[Toast 提示]
    end

    subgraph "状态层"
        HSTORE[health-store]
        RSTORE[report-store]
        CSTORE[chat-store]
        USTORE[upload-store]
        LLMS[llm-observe-store]
    end

    subgraph "API 层"
        API[api.ts fetchWithAuth]
    end

    DASH & BIG & RPT & CHAT & UPLOAD & TEST & MED & LLMOBS --> HEADER
    DASH & BIG --> LINECHART & KPICARD
    DASH --> HSTORE
    RPT --> RSTORE
    CHAT --> CSTORE
    UPLOAD --> USTORE
    LLMOBS --> LLMS
    HSTORE & RSTORE & CSTORE & USTORE & LLMS --> API
```

---

## 模块索引

| 模块路径 | 职责 | 入口文件 | 关键文件 |
|---------|------|---------|---------|
| `app/dashboard` | 仪表盘页面 | `page.tsx` | KPI 卡片、年度跑量图表、跑步/睡眠面板 |
| `app/bigscreen` | 数据大屏页面 | `page.tsx` | 6 KPI 网格、年度跑量图、训练状态面板 |
| `app/report` | AI 健康报告 | `page.tsx` | Markdown 渲染、报告列表、PDF 下载 |
| `app/chat` | Chat 智能助手 | `page.tsx` | 对话界面、意图识别、多轮对话 |
| `app/upload` | 文件上传分析 | `page.tsx` | 数据文件/医学报告/图像上传、OCR、入库 |
| `app/test-report` | 测试报告 | `page.tsx` | E2E 报告列表、文件下载（带认证） |
| `app/medical` | 医疗报告 | `page.tsx` | 5 Tab（综合分析/时间线/用药/化验/健康画像） |
| `app/llm-observe` | LLM 观测 | `page.tsx` | LLM 调用指标、Trace 列表、优化建议 |
| `components/layout` | 共享布局 | `header.tsx` | 统一 Header（导航栏+品牌标识+日期+返回按钮） |
| `components/charts` | 图表组件 | `line-chart.tsx` | ECharts 折线图（面积渐变+空数据兜底） |
| `components/dashboard` | 数据组件 | `kpi-card.tsx` | KPI 状态卡片 |
| `components/ui` | UI 组件 | `toast.tsx` | 全局错误提示 |
| `lib/stores` | Zustand 状态 | `health-store.ts`, `report-store.ts`, `llm-observe-store.ts` | 健康数据/报告/LLM 观测状态 |
| `lib/hooks` | Hook 工具 | `use-error-toast.ts` | 错误提示 Hook |
| `lib/api` | API 调用层 | `api.ts` | fetchWithAuth 封装（Bearer token） |
| `lib/utils` | 共享工具 | `utils.ts` | `v()` 空安全显示、`formatPace()` 配速格式化 |
| `types` | TypeScript 类型 | `health.ts` | HealthData, Report 等 |
| `tests` | E2E 测试 | `e2e_test.py` | 10 轮全链路测试 + MD/HTML/PDF 报告 |

---

## 页面路由

| 路径 | 页面 | 状态 | 功能 |
|------|------|------|------|
| `/` | 重定向 | ✅ 已完成 | → `/dashboard` |
| `/dashboard` | 仪表盘 | ✅ 已完成 | 健康数据 KPI、跑步/睡眠面板、年度跑量图表 |
| `/bigscreen` | 数据大屏 | ✅ 已完成 | 6 KPI 网格、训练状态、年度跑量 |
| `/report` | AI 报告 | ✅ 已完成 | Markdown 渲染、报告列表、PDF 下载 |
| `/chat` | Chat 助手 | ✅ 已完成 | 多轮对话、文件上传分析、流式响应 |
| `/upload` | 文件上传 | ✅ 已完成 | CSV/JSON/PDF/图像/TXT 上传、多模态 AI 分析、数据入库 |
| `/test-report` | 测试报告 | ✅ 已完成 | E2E 报告列表、认证文件下载 |
| `/medical` | 医疗报告 | ✅ 已完成 | 5 Tab（综合分析/时间线/用药/化验/健康画像） |
| `/llm-observe` | LLM 观测 | ✅ 已完成 | LLM 调用指标、Trace 列表、成本统计、优化建议 |

---

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Next.js | 16.2.6 | App Router 框架（静态导出模式） |
| React | 19.2.4 | UI 库 |
| TypeScript | 5.x | 类型系统 |
| Zustand | 5.0.13 | 状态管理 |
| ECharts | 6.0.0 | 图表渲染（面积渐变） |
| Leaflet | 1.9.4 | 地图渲染（待用） |
| React-Leaflet | 5.0.0 | React Leaflet 封装 |
| Recharts | 3.8.1 | 图表渲染（备用） |
| Tailwind CSS | 4.x | 样式框架 |
| Google Chrome | headless | HTML → A4 PDF 转换 |
| Python 3 | curl subprocess | E2E 测试引擎 |

---

## 运行与开发

```bash
# 安装依赖
npm install

# 开发模式
npm run dev

# 构建生产版本（本地 Mac 执行，不上传服务器构建）
npm run build

# 代码检查
npm run lint
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NEXT_PUBLIC_API_URL` | `/qm/api` | 后端 API 地址（生产相对路径） |

### 生产部署

- **构建模式**: `output: "export"` 静态导出（不需要 Node.js 运行时）
- **basePath**: `/qm`（所有资源路径以 `/qm/` 开头）
- **构建**: 本地 `npm run build` → `tar czf` → `scp` 到服务器
- **API 前缀**: 后端路由 `/qm/api/`，前端 `API_BASE` 为 `/qm/api`
- **导航**: 使用 Next.js `Link` 组件自动处理 basePath

---

## 测试

### E2E 测试

```bash
# 运行 10 轮全链路测试，生成 MD + HTML + PDF 报告
python3 tests/e2e_test.py

# 测试并上传报告到服务器
python3 tests/e2e_test.py --upload
```

**测试覆盖（15 用例/轮）：**
- 页面加载（首页、仪表盘、大屏、报告、测试报告）× 10 轮
- API 端点（Dashboard、Reports、Test Reports）× 10 轮
- 数据完整性（7 项数据断言：profile、training、running、sleep）× 10 轮

**报告规范：**
- `e2e-report.md` — Markdown 文本报告
- `e2e-report.html` — 深色主题 HTML（SVG 图表内联嵌入）
- `e2e-report.pdf` — A4 规格，Chrome headless 从 HTML 转换
- `e2e-charts.svg` — 响应时间趋势图（含通过率甜甜圈图）

---

## 设计系统

### 主题色

```css
--primary: #00C9A7;     /* 青沐生命青绿色 */
--secondary: #00A99D;   /* 次要色 */
--accent: #00D4FF;     /* 强调色 */
--background: #111111; /* 深色背景 */
--surface: #1A1A1A;    /* 卡片背景 */
--surface-elevated: #222222; /* 悬停态 */
--border: #333333;      /* 边框 */
--success: #00C9A7;
--warning: #FFB800;
--error: #FF4757;
```

---

## 数据流

```
用户操作
   ↓
Zustand Store (health-store / report-store / chat-store / upload-store / llm-observe-store)
   ↓
API 层 (lib/api.ts) → fetchWithAuth (Bearer token)
   ↓
后端 API (aisport.tech/qm/api/)
   ↓
组件渲染 (Header / LineChart / KpiCard / DataCell / MetricRow)
```

---

## 关键设计决策

| 决策 | 原因 |
|------|------|
| 共享 `Header` 组件 | 消除 ~30 行重复代码，统一导航栏和返回按钮 |
| `v()` 空安全函数 | 替代 `||` 运算符，避免值为 0 时错误显示 `-` |
| LineChart 始终渲染容器 | 修复异步数据加载后 ECharts 不渲染的 bug |
| `next/font/local` 替代 `next/font/google` | 消除构建时 Google Fonts 网络依赖 |
| 报告 MD + HTML(内联SVG) → A4 PDF | reportlab 无法嵌入 SVG，改用浏览器渲染 |
| 文件下载用 JS fetch + blob | API 需 Authorization header，`<a>` 直连无法携带 |

---

## 覆盖报告

| 指标 | 数值 |
|------|------|
| 源文件数 | 20+ |
| 已扫描文件数 | 20+ |
| 覆盖百分比 | **100%** |
| 模块数量 | 16+ |
| 已生成 CLAUDE.md | 5 (1 根级 + 4 子模块) |
| 导航面包屑 | 已添加（根 CLAUDE.md） |

---

## 相关文件清单

| 文件 | 用途 |
|------|------|
| `next.config.ts` | basePath + 静态导出配置 |
| `src/app/layout.tsx` | 根布局（Inter 本地字体） |
| `src/app/globals.css` | 全局样式、CSS 变量 |
| `src/lib/utils.ts` | 共享工具函数 |
| `src/components/layout/header.tsx` | 统一 Header 组件（含返回按钮） |
| `src/lib/stores/llm-observe-store.ts` | LLM 观测状态管理 |
| `tests/e2e_test.py` | E2E 测试 + 报告生成脚本 |
