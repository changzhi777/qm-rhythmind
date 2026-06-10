[根目录](../../../../CLAUDE.md) > [src](../../) > [components](../) > **charts**

# charts 模块 — ECharts 图表组件

> **最后更新:** 2026-06-10T18:00:00+08:00

---

## 模块职责

封装 ECharts 6.0.0，提供深色主题的折线图组件，支持响应式 resize、主题色配置、空数据兜底、InfluxDB 时序数据可视化。

---

## 文件清单

| 文件 | 组件 | 行数 | 说明 |
|------|------|------|------|
| `line-chart.tsx` | `LineChart` | 95 | 通用折线面积图（静态数据） |
| `influx-time-series-chart.tsx` | `InfluxTimeSeriesChart` | 143 | InfluxDB 时序数据图表（自动 fetch + loading/空状态） |

---

## LineChart 组件 (line-chart.tsx)

### Props

```typescript
interface LineChartProps {
  title?: string;                                    // 图表标题
  data: { name: string; value: number }[];            // 数据数组
  height?: number;                                   // 高度（默认 300）
  color?: string;                                    // CSS 变量或 hex（默认 var(--primary)）
  unit?: string;                                     // 单位（用于 tooltip）
}
```

### 颜色映射

| CSS 变量 | HEX | 说明 |
|---------|-----|------|
| `var(--primary)` | `#00C9A7` | 主题绿 |
| `var(--secondary)` | `#00A99D` | 次要绿 |
| `var(--accent)` | `#00D4FF` | 强调蓝 |

### 内部架构

```
useEffect #1 (mount)
  └─ echarts.init(div, 'dark') + window resize listener
     └─ cleanup: removeEventListener + chart.dispose()

useEffect #2 (data, title, color, unit change)
  ├─ data.length === 0 → chart.clear()
  └─ data.length > 0 → chart.setOption({...})
```

### ECharts 配置细节

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `backgroundColor` | `transparent` | 继承暗色背景 |
| `tooltip.trigger` | `axis` | 十字准线 |
| `grid` | `left:10% right:5% top:5-15% bottom:10%` | 有标题时上边距 15% |
| `xAxis.axisLabel.color` | `#888` | 灰白色标签 |
| `yAxis.splitLine.color` | `#333, dashed` | 虚线网格 |
| `series.type` | `line` | 平滑曲线 |
| `series.smooth` | `true` | — |
| `series.symbol` | `circle, size:6` | 圆形数据点 |
| `areaStyle` | `LinearGradient(0,0,0,1)` | 颜色 33% → 05% 透明度渐变 |

### 关键设计决策

| 决策 | 原因 |
|------|------|
| 始终渲染容器 div | 不因空数据提前 return，避免 useEffect 竞态 |
| 两个 useEffect 分离 | init（mount 一次）和 setOption（data change）独立 |
| `chart.clear()` 不 dispose | 清空数据但保留实例，新数据到达时可恢复 |
| `COLOR_MAP` 静态映射 | CSS 变量在 canvas 中不生效，需转为 hex |

---

## InfluxTimeSeriesChart 组件 (influx-time-series-chart.tsx)

### Props

```typescript
interface InfluxTimeSeriesChartProps {
  metric: string;                   // heart_rate_avg / steps / sleep_hours / hrv
  metricLabel?: string;             // 显示标签
  range?: string;                   // -7d / -30d（默认 -7d）
  aggregation?: string;             // 1d / 1h / 1w（默认 1d）
  fn?: 'mean' | 'max' | 'min' | 'last';  // 聚合函数（默认 mean）
  color?: string;                   // hex 颜色（默认 #00C9A7）
  height?: number;                  // 高度（默认 240）
}
```

### FetchState 状态机

```typescript
type FetchState =
  | { kind: 'loading' }                                    // 初始/加载中
  | { kind: 'ok'; data: InfluxTimeSeriesResponse }         // 数据就绪
  | { kind: 'empty'; message?: string };                   // 无数据/错误
```

### 三层 useEffect 架构

```
useEffect #1 (数据获取)   — metric/range/aggregation/fn 变化时
  └─ api.getInfluxTimeSeries() → setState({kind:'ok'|'empty'})
     └─ cancelled 标志防止竞态

useEffect #2 (图表初始化) — mount 一次
  └─ echarts.init(div, 'dark') + resize listener
     └─ cleanup: dispose

useEffect #3 (数据渲染)   — state/color 变化时
  ├─ state.kind !== 'ok' → chart.clear()
  └─ state.kind === 'ok' → chart.setOption({...})
```

### 渲染三态

| 状态 | 渲染内容 |
|------|---------|
| `loading` | 半透明遮罩 + "加载中..." |
| `empty` | "暂无时序数据" / 错误信息 |
| `ok` | ECharts 折线面积图（同 LineChart 风格） |

---

## 公共 ECharts 配置模式

两个组件共享以下配置规范：

| 配置 | 值 | 共享原因 |
|------|-----|---------|
| 主题 | `'dark'` | 全局暗色背景 |
| tooltip 背景 | `rgba(26,26,26,0.9)` | `var(--surface)` 等效 |
| 网格线颜色 | `#333` | `var(--border)` 等效 |
| 标签颜色 | `#888` | 可读性 |
| 面积渐变 | 33% → 05% 透明度 | 视觉一致性 |
| 圆角数据点 | `circle, size:6` | — |
| resize 处理 | `window.addEventListener('resize')` | 响应式 |

---

## 使用示例

```tsx
// 静态数据
<LineChart
  data={yearlyChart}
  height={220}
  color="var(--primary)"
  unit="km"
/>

// 时序数据（自动 fetch + loading）
<InfluxTimeSeriesChart
  metric="heart_rate_avg"
  metricLabel="平均心率"
  range="-7d"
  aggregation="1d"
  fn="mean"
  color="#00C9A7"
  height={240}
/>
```

---

## 变更记录 (Changelog)

- **2026-06-10** 深化：补充 InfluxTimeSeriesChart 完整 API、FetchState 状态机、三层 useEffect 架构、渲染三态、公共配置模式表
- **2026-05-18** 首次 AI 上下文初始化
