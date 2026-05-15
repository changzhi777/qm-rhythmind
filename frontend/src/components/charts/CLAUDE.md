[根目录](../../../CLAUDE.md) > [src](../../) > [components](../) > **charts**

# charts 模块 — ECharts 图表组件

> **最后更新:** 2026-05-15T14:22:35+08:00

---

## 模块职责

封装 ECharts 6.0.0，提供深色主题的折线图组件（LineChart），支持响应式 resize 和主题色配置。

---

## 文件清单

| 文件 | 组件 | 说明 |
|------|------|------|
| `line-chart.tsx` | `LineChart` | 折线趋势图 |

---

## LineChart 组件

### Props

```typescript
interface LineChartProps {
  title?: string;                    // 图表标题
  data: { name: string; value: number }[];  // 数据数组
  height?: number;                   // 高度 (默认 300)
  color?: string;                   // 颜色 (默认 var(--primary))
}
```

### 使用示例

```tsx
<LineChart
  data={[
    { name: '周一', value: 5.2 },
    { name: '周二', value: 3.8 },
    { name: '周三', value: 6.1 },
  ]}
  height={200}
  color="var(--primary)"
/>
```

### 颜色映射

| CSS 变量 | HEX 值 |
|---------|-------|
| `var(--primary)` | `#00C9A7` |
| `var(--secondary)` | `#00A99D` |
| `var(--accent)` | `#00D4FF` |

### ECharts 配置

- **背景**: transparent（继承父容器）
- **Tooltip**: 触发类型 `axis`，深色半透明背景
- **坐标轴**: 浅灰色 `#333` 分割线，虚线
- **折线**: 平滑曲线 `smooth: true`，圆形节点

### 生命周期

1. `useEffect` (mount) — 初始化 ECharts 实例，绑定 resize 监听
2. `useEffect` (data change) — 更新图表配置
3. `useEffect` (unmount) — 移除监听，dispose 实例

---

## 常见问题 (FAQ)

**Q: 如何添加 legend？**
A: 手动在 `option` 中添加 `legend` 配置项。

**Q: 如何添加多系列？**
A: 在 `series` 数组中添加多个对象即可。

**Q: 图表不响应窗口 resize？**
A: 确保父容器有明确宽度，组件会自动监听 `window.resize`。

---

## 相关文件

- `/src/app/dashboard/page.tsx` — 仪表盘使用
- `/src/app/bigscreen/page.tsx` — 数据大屏使用
- `/src/app/globals.css` — 主题色 CSS 变量定义