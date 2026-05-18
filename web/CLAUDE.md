# CLAUDE.md — web/ Vue.js 替代前端

> `[根目录(../CLAUDE.md) > **web**`

---

## 模块职责

单文件 Vue.js 3 + ECharts + Three.js 健康仪表盘前端，不依赖 Node.js 构建工具链。通过 CDN 加载依赖，由 FastAPI StaticFiles 或 nginx 直接服务。

---

## 技术方案

- **Vue.js 3** (CDN `vue.global.prod.js`)
- **ECharts 5** (CDN) — 数据图表
- **Three.js 0.160** (ESM importmap) — 3D 体素头像
- **html2pdf.js** — PDF 导出
- **marked.js** — Markdown 渲染（AI 报告）

---

## 文件结构

```
web/
├── index.html    # 单文件应用（619 行，Vue 3 SFC + 3D + ECharts）
└── style.css     # 暗色主题样式（272 行，CSS 变量）
```

---

## 对外接口

由 `scripts/run_ingestion.py --serve` 在 `localhost:8088` 启动，路由：
- `GET /` — `index.html`
- `GET /static/*` — CSS 等静态资源
- `GET /qm/api/dashboard` — 仪表盘数据（通过 dashboard_router）
- `GET /qm/api/reports` — AI 报告列表
- `POST /qm/api/analyze` — 触发 AI 分析

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

- `web/` 是早期快速原型，单文件无需构建
- `frontend/` 是生产版本（Next.js 16，部署到 `aisport.tech/qm`）
- 两者功能重叠，`web/` 适用于本地开发和演示

---

## 变更记录 (Changelog)

- **2026-05-18** 首次 AI 上下文初始化
