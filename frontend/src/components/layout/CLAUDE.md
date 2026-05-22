[根目录](../../../../CLAUDE.md) > [src](../../) > [components](../) > **layout**

# layout 模块 — 共享布局组件

> **最后更新:** 2026-05-22T08:00:00+08:00

---

## 模块职责

提供跨页面共享的布局组件，统一品牌标识、导航栏、页面标题、返回按钮，消除页面间的重复代码。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `header.tsx` | 统一 Header（品牌 Logo + 返回按钮 + 导航链接 + 日期 + 额外操作区） |

---

## Header 组件

### Props

```typescript
interface HeaderProps {
  title: string;        // 页面副标题（如 "健康仪表盘"）
  activePath?: string;  // 当前高亮导航路径（如 "/dashboard"）
  maxWidth?: string;    // 内容区最大宽度（默认 1200px）
  showDate?: boolean;   // 是否显示日期（客户端渲染，避免 hydration 不匹配）
  showBack?: boolean;   // 是否显示返回按钮（默认 true）
  extra?: ReactNode;    // 右侧额外区域（如报告页的"重新分析"按钮）
}
```

### 使用示例

```tsx
<Header title="健康仪表盘" activePath="/dashboard" />
<Header title="数据大屏" activePath="/bigscreen" maxWidth="1400px" showDate />
<Header title="报告" activePath="/report" extra={<button>重新分析</button>} />
<Header title="Chat 助手" activePath="/chat" />
<Header title="文件上传" activePath="/upload" />
```

### 导航项

| 路径 | 标签 |
|------|------|
| `/dashboard` | 仪表盘 |
| `/bigscreen` | 大屏 |
| `/report` | 报告 |
| `/chat` | Chat |
| `/upload` | 上传 |
| `/test-report` | 测试 |
| `/llm-observe` | 观测 |

使用 Next.js `Link` 组件，自动处理 `basePath: "/qm"`。

### 返回按钮

- 所有页面默认显示返回按钮
- 使用 `router.back()` 返回上一页
- 首页（dashboard）隐藏返回按钮

---

## 相关文件

- `/src/app/dashboard/page.tsx` — 使用 Header
- `/src/app/bigscreen/page.tsx` — 使用 Header（showDate）
- `/src/app/report/page.tsx` — 使用 Header（extra 按钮）
- `/src/app/chat/page.tsx` — 使用 Header（待开发）
- `/src/app/upload/page.tsx` — 使用 Header（待开发）
- `/src/app/test-report/page.tsx` — 使用 Header
