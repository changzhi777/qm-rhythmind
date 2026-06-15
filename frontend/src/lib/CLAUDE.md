[根目录](../../../CLAUDE.md) > [src](../../) > **lib**

# lib 模块 — 工具库与状态管理

> **最后更新:** 2026-06-11T13:30:00+08:00

---

## 模块职责

提供 API 调用封装、Zustand 状态管理、共享工具函数和自定义 Hook。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `api.ts` | API 调用层（`fetchWithAuth<T>` 泛型 + 401 拦截 + Bearer 头 + 各端点封装） |
| `utils.ts` | 共享工具函数（`v()` 空安全、`formatPace()` 配速、`yearlyToChart()` 年度数据转换） |
| `stores/health-store.ts` | 健康数据 Zustand 状态（5 分钟缓存） |
| `stores/report-store.ts` | AI 报告 Zustand 状态（含下载状态） |
| `stores/llm-observe-store.ts` | LLM 观测 Zustand 状态（指标/Trace/建议） |
| `hooks/use-auto-refresh.ts` | 定时刷新 Hook（2026-06-10 新增） |
| `hooks/use-error-toast.ts` | 错误提示 Hook |

---

## utils.ts

```typescript
v(val: unknown): string | number         // null/undefined → '-'，否则原值
formatPace(paceMinPerKm): string         // 5.1 → 5'06" 跑步配速格式
yearlyToChart(yearly): Array<[string, number]>  // 年度活动数据 → ECharts 数据集
```

**Why `v()` instead of `||`**: `val || '-'` 在值为 `0` 时错误显示 `-`，`v()` 仅在 `null`/`undefined` 时显示占位符。

---

## api.ts

### 接口

```typescript
api.getDashboard()                                  // GET /dashboard
api.getReports(limit?)                              // GET /reports?limit=N
api.getReport(id)                                   // GET /reports/:id
api.downloadReport(id): Promise<Blob>               // GET /reports/:id/download
api.triggerAnalyze()                                // POST /analyze
api.uploadHealth(data)                              // POST /v1/health/upload
api.getUsersSummary()                               // GET /users/summary
api.getInfluxTimeSeries(metric, range?, agg?, fn?)  // GET /influxdb/timeseries  (2026-06-10 新增)
```

### fetchWithAuth\<T\>（核心）

```typescript
fetchWithAuth<T>(endpoint: string, options?: RequestInit): Promise<T>
```

**行为：**
1. 自动注入 `Authorization: Bearer <token>` 头（token 从 `getAuthToken()` 取）
2. 自动注入 `Content-Type: application/json`
3. **401 拦截**：清除 `auth_token` + `user_display` localStorage，强制 `window.location.href = '/'` 跳回首页
4. 非 2xx：抛 `Error('API Error: <status> <statusText>')`

### 认证

```typescript
getAuthToken()   // localStorage('auth_token') || ''，SSR 时返回 ''
setAuthToken(t)  // localStorage.setItem('auth_token', t)，SSR 时无操作
```

### 类型导出

```typescript
interface UserSummary {
  user_id: string;
  display_name: string;
  avatar: string;
  facts_count: number;
  has_medical: boolean;
  profile: { age?; gender?; vo2_max?; bmi? };
  running?: { total_runs?; total_km?; avg_pace_min_per_km? };
  active_medications?: number;
  abnormal_labs?: number;
}

interface InfluxDataPoint { ts: string; value: number }
interface InfluxTimeSeriesResponse {
  status: 'ok' | 'degraded';
  metric: string; range: string; aggregation: string; fn: string;
  data: InfluxDataPoint[];
  count: number; latest: number | null; avg: number | null;
  error?: string;
}
```

### API 路径

```typescript
API_BASE  // 默认 /qm/api（可由 NEXT_PUBLIC_API_URL 覆盖）
V1_BASE   // = API_BASE.replace('/qm/api', '/api')，用于 /api/v1/* 端点
```

---

## hooks/use-auto-refresh.ts（2026-06-10 新增）

```typescript
useAutoRefresh(intervalMs: number, callback: () => void | Promise<void>, enabled?: boolean): void
```

**用途：** 仪表盘/大屏页面定时刷新数据（默认 5 分钟）。

**实现要点：**
- 使用 `useRef` 保存最新 callback，避免 setInterval 闭包陈旧
- `enabled === false` 时不启动定时器
- 卸载时 `clearInterval`

---

## stores/health-store

### State

```typescript
interface HealthState {
  data: HealthData;          // 键值对健康数据
  loading: boolean;
  error: string | null;
  lastFetch: number | null;  // 5分钟缓存时间戳
  fetchDashboard: () => Promise<void>;
  clearData: () => void;
}
```

### 选择器

```typescript
selectProfile(state)        // vo2_max, bmi, weight_kg, age, resting_hr, max_hr
selectTraining(state)       // training.metrics
selectSleep(state)          // sleep.summary
selectRunning(state)        // running.summary
selectYearlyActivity(state) // activity_summary.yearly
```

### 缓存策略

- **5 分钟防抖**：`lastFetch` 距今不足 5 分钟时跳过请求
- **JSON 解析**：自动解析 API 返回中的字符串化 JSON 对象

---

## stores/report-store

### State

```typescript
interface ReportState {
  reports: Report[];
  currentReport: Report | null;
  loading: boolean;
  analyzing: boolean;
  downloading: boolean;  // 下载状态（UI 显示"下载中..."）
  error: string | null;
  fetchReports: () => Promise<void>;
  fetchReport: (id: number) => Promise<void>;
  triggerAnalyze: () => Promise<void>;
  downloadReport: (id: number) => Promise<void>;
  clearCurrent: () => void;
}
```

### 下载流程

1. `downloading: true`（UI 显示加载状态并禁用按钮）
2. `api.downloadReport(id)` → Blob
3. 创建 `<a>` 标签触发浏览器下载
4. 清理 `URL.revokeObjectURL`

---

## stores/llm-observe-store

### State

```typescript
interface LlmObserveState {
  metrics: MetricsResponse | null;
  traces: TraceItem[];
  suggestions: Suggestion[];
  loading: boolean;
  error: string | null;
  days: number;
  fetchMetrics: (days?) => Promise<void>;
  fetchTraces: (limit?, offset?) => Promise<void>;
  fetchSuggestions: (days?) => Promise<void>;
}
```

---

## 相关文件

- `/src/types/health.ts` — 类型定义
- `/src/components/layout/header.tsx` — 使用 stores、读取 `user_display` localStorage
- `/src/components/charts/influx-time-series-chart.tsx` — 调用 `api.getInfluxTimeSeries()`（2026-06-10 新增）
- `/src/app/dashboard/page.tsx` — 使用 health-store + `useAutoRefresh`
- `/src/app/bigscreen/page.tsx` — 使用 health-store + `useAutoRefresh`
- `/src/app/report/page.tsx` — 使用 report-store
- `/src/app/llm-observe/page.tsx` — 使用 llm-observe-store
- `/src/app/page.tsx`（用户选择首页）— 调用 `setAuthToken(userId)` 写入用户 ID 作为 dev token

---

## 变更记录 (Changelog)

- **2026-06-11** 深化：补充 `fetchWithAuth<T>` 泛型签名、401 拦截逻辑、`getInfluxTimeSeries` 端点、`useAutoRefresh` hook、`UserSummary`/`InfluxTimeSeriesResponse` 类型字段、`yearlyToChart` 工具函数
- **2026-05-27** 增量更新：新增 V1_BASE、setAuthToken、Users Summary API、llm-observe-store
- **2026-05-15** 首次 AI 上下文初始化
