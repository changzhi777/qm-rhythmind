[根目录](../../../../CLAUDE.md) > [src](../../) > [components](../) > **layout**

# layout 模块 — 共享布局组件

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

提供跨页面共享的布局组件，统一品牌标识、导航栏、页面标题、返回按钮、用户头像，消除页面间的重复代码。

---

## 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `header.tsx` | 133 | 统一 Header（品牌 Logo + 导航 + 返回 + 用户头像 + 日期 + 额外操作区） |

---

## Header 组件

### Props

```typescript
interface HeaderProps {
  title: string;            // 页面副标题（如 "健康仪表盘"）
  activePath?: string;      // 当前高亮导航路径
  maxWidth?: string;        // 内容区最大宽度（默认 "1200px"）
  showDate?: boolean;       // 显示日期（客户端渲染，避免 hydration）
  showBack?: boolean;       // 显示返回按钮（默认 true）
  extra?: React.ReactNode;  // 右侧额外区域（如报告页"重新分析"按钮）
}
```

### 内部状态

| 变量 | 类型 | 说明 |
|------|------|------|
| `mounted` | `boolean` | `setTimeout(0)` 延迟挂载，避免 SSR hydration 不匹配 |

### 布局结构

```
┌──────────────────────────────────────────────────────────────┐
│ ← 返回 │ [R] RHYTHMIND 律动 v0.2.0         日期 │ extra │ [头像] name │
│         │ 仪表盘 · 大屏 · 报告 · ... — title                │
└──────────────────────────────────────────────────────────────┘
```

**三段式布局**:
1. **左侧**: 返回按钮 (可选) + Logo + 品牌名 + 导航面包屑 + 页面标题
2. **右侧**: 日期 (可选) + extra 插槽 + 用户头像/名称

### 导航项

| 路径 | 标签 | 排序 |
|------|------|------|
| `/dashboard` | 仪表盘 | 1 |
| `/bigscreen` | 大屏 | 2 |
| `/report` | 报告 | 3 |
| `/medical` | 医疗 | 4 |
| `/chat` | Chat | 5 |
| `/upload` | 上传 | 6 |
| `/test-report` | 测试 | 7 |
| `/llm-observe` | 观测 | 8 |

使用 Next.js `<Link>`，自动处理 `basePath: "/qm"`。激活态：`var(--primary)` + `font-weight: 500`。

### 用户头像逻辑

```
getUserDisplay()
  ├─ SSR → { avatar: '?', name: '' }
  └─ Client:
      ├─ localStorage('user_display') 有效 → 解析并返回
      └─ 无效/不存在 → { avatar: '?', name: getAuthToken() }

点击头像 → Link to "/"
  └─ onClick: localStorage.removeItem('auth_token') + removeItem('user_display')
```

### 显示条件

| 元素 | 条件 |
|------|------|
| 返回按钮 | `showBack && !isHome`（首页隐藏） |
| 日期 | `showDate && mounted`（仅客户端渲染） |
| 用户头像 | `mounted`（仅客户端渲染） |
| extra 插槽 | `extra` prop 非空 |

### 使用示例

```tsx
<Header title="健康仪表盘" activePath="/dashboard" />                   // 首页
<Header title="数据大屏" activePath="/bigscreen" maxWidth="1400px" showDate />
<Header title="AI 健康报告" activePath="/report" extra={<button>⚡ 重新分析</button>} />
<Header title="Chat 助手" activePath="/chat" />
<Header title="文件上传分析" activePath="/upload" />
<Header title="医疗报告" activePath="/medical" />
<Header title="LLM 观测" activePath="/llm-observe" />
```

### CSS 类名规范

| 类名 | 用途 | 定义位置 |
|------|------|---------|
| `.header-back-btn` | 返回按钮 hover 态 | `globals.css` |
| `.header-user-avatar` | 用户头像样式 | `globals.css` |

### 关键设计决策

| 决策 | 原因 |
|------|------|
| `mounted` 延迟渲染 | 避免 SSR/CSR hydration 日期和用户信息不匹配 |
| `router.back()` 返回 | 不硬编码 `href`，支持跨页面跳转后正确返回 |
| `isHome = activePath === '/dashboard'` | 仪表盘视为首页，隐藏返回按钮 |
| 退出清 `auth_token` + `user_display` | 401 拦截也清 auth_token，双重保障 |

---

## 使用统计

所有 8 个页面均使用 Header：

| 页面 | showDate | showBack | extra |
|------|----------|----------|-------|
| `/dashboard` | — | 自动隐藏 (isHome) | — |
| `/bigscreen` | ✅ | ✅ | — |
| `/report` | — | ✅ | ✅ 重新分析按钮 |
| `/medical` | — | ✅ | — |
| `/chat` | — | ✅ | — |
| `/upload` | — | ✅ | — |
| `/test-report` | — | ✅ | — |
| `/llm-observe` | — | ✅ | — |

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：补充布局结构 ASCII 图、内部状态说明、用户头像完整逻辑流、显示条件矩阵、CSS 类名规范、8 页面使用统计、设计决策表
- **2026-05-27** 首次 AI 上下文初始化
