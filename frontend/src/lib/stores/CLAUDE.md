[根目录](../../../CLAUDE.md) > [src](../../) > **stores**

# stores 模块 — Zustand 状态管理

> **最后更新:** 2026-05-27T10:50:56+08:00

---

## 模块职责

Zustand 5 状态管理，提供健康数据（health-store）、报告数据（report-store）和 LLM 观测（llm-observe-store）的全局状态管理，包含缓存、错误处理、下载状态跟踪。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `health-store.ts` | 健康数据状态（含选择器） |
| `report-store.ts` | AI 报告状态（含下载状态） |
| `llm-observe-store.ts` | LLM 观测状态（指标/Trace/建议） |

---

## health-store

### State 接口

```typescript
interface HealthState {
  data: HealthData;           // 键值对健康数据
  loading: boolean;
  error: string | null;
  lastFetch: number | null;   // 时间戳，5分钟缓存

  fetchDashboard: () => Promise<void>;
  clearData: () => void;
}
```

### 选择器

```typescript
selectProfile(state)      // gender, age, height_cm, weight_kg, bmi, vo2_max, resting_hr, max_hr
selectTraining(state)     // training.metrics
selectSleep(state)        // sleep.summary
selectRunning(state)       // running.summary
selectYearlyActivity(state) // activity_summary.yearly
```

### 数据键名约定

| 键名格式 | 示例值 |
|---------|-------|
| `profile.*` | `profile.age`, `profile.bmi`, `profile.vo2_max` |
| `training.metrics` | `{ readiness_score, acwr, endurance_score, hill_score }` |
| `running.summary` | `{ avg_pace_min_per_km, total_distance, total_runs }` |
| `sleep.summary` | `{ avg_total_hours, deep_pct }` |
| `activity_summary.yearly` | `Record<year, { distance, count }>` |

### 缓存策略

- **5 分钟防抖**：如果 `lastFetch` 距今不足 5 分钟，跳过请求

---

## report-store

### State 接口

```typescript
interface ReportState {
  reports: Report[];
  currentReport: Report | null;
  loading: boolean;
  analyzing: boolean;
  downloading: boolean;
  error: string | null;

  fetchReports: () => Promise<void>;
  fetchReport: (id: number) => Promise<void>;
  triggerAnalyze: () => Promise<void>;
  downloadReport: (id: number) => Promise<void>;
  clearCurrent: () => void;
}
```

### Report 类型

```typescript
interface Report {
  id: number;
  content: string;      // Markdown 格式
  model: string;        // AI 模型名称
  timestamp: string;    // ISO 时间戳
  is_current?: boolean;
}
```

### 下载流程

1. 设置 `downloading: true`
2. 调用 `api.downloadReport(id)` 获取 Blob
3. 创建 `<a>` 标签触发下载
4. 清理 URL 对象

---

## llm-observe-store

### State 接口

```typescript
interface LlmObserveState {
  metrics: MetricsResponse | null;
  traces: TraceItem[];
  suggestions: Suggestion[];
  loading: boolean;
  error: string | null;
  days: number;

  fetchMetrics: (days?: number) => Promise<void>;
  fetchTraces: (limit?: number, offset?: number) => Promise<void>;
  fetchSuggestions: (days?: number) => Promise<void>;
}
```

API 路径: `/qm/api/v1/llm-observe/*`

---

## 常见问题 (FAQ)

**Q: 如何扩展新的数据类型？**
A: 在 `types/health.ts` 的 `HealthData` 接口中添加新键，在 `health-store.ts` 的选择器中导出新的选择器函数。

**Q: 如何清除缓存强制刷新？**
A: 调用 `clearData()` 后再调用 `fetchDashboard()`。

---

## 相关文件

- `/src/lib/api.ts` — API 调用层
- `/src/types/health.ts` — 类型定义
- `/src/app/dashboard/page.tsx` — 使用 health-store
- `/src/app/bigscreen/page.tsx` — 使用 health-store
- `/src/app/report/page.tsx` — 使用 report-store
- `/src/app/llm-observe/page.tsx` — 使用 llm-observe-store
