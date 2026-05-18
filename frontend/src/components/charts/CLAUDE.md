[根目录](../../../../CLAUDE.md) > [src](../../) > [components](../) > **charts**

# charts 模块 — ECharts 图表组件

> **最后更新:** 2026-05-18T12:22:25+08:00

---

## 模块职责

封装 ECharts 6.0.0，提供深色主题的折线面积图组件，支持响应式 resize、主题色配置和空数据兜底。

---

## 文件清单

| 文件 | 组件 | 说明 |
|------|------|------|
| `line-chart.tsx` | `LineChart` | 折线面积图（渐变填充） |

---

## LineChart 组件

### Props

```typescript
interface LineChartProps {
  title?: string;                    // 图表标题
  data: { name: string; value: number }[];  // 数据数组
  height?: number;                   // 高度 (默认 300)
  color?: string;                   // 颜色 (默认 var(--primary))
  unit?: string;                    // 单位（用于 tooltip）
}
```

### 颜色映射

| CSS 变量 | HEX 值 |
|---------|-------|
| `var(--primary)` | `#00C9A7` |
| `var(--secondary)` | `#00A99D` |
| `var(--accent)` | `#00D4FF` |

### 设计要点

- **始终渲染容器 div**：不因空数据提前 return，避免 useEffect 竞态 bug
- **面积渐变填充**：`areaStyle` 使用 `LinearGradient`（33% → 05% 透明度）
- **空数据时调用 `chart.clear()`**：清空图表但不销毁实例
- **两个 useEffect 分离**：init（mount）和 setOption（data change）独立管理

### 使用示例

```tsx
<LineChart data={yearlyChart} height={220} color="var(--primary)" unit="km" />
```

---

## 相关文件

- `/src/app/dashboard/page.tsx` — 仪表盘年度跑量图表
- `/src/app/bigscreen/page.tsx` — 大屏年度跑量图表
- `/src/app/globals.css` — 主题色 CSS 变量
