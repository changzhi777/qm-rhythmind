[根目录](../../../CLAUDE.md) > [src](../../) > **lib**

# lib 模块 — 工具库与状态管理

> **最后更新:** 2026-05-27T10:50:56+08:00

---

## 模块职责

提供 API 调用封装、Zustand 状态管理、共享工具函数和自定义 Hook。

---

## 文件清单

| 文件 | 职责 |
|------|------|
| `api.ts` | API 调用层（fetchWithAuth + 各端点封装） |
| `utils.ts` | 共享工具函数（`v()` 空安全显示、`formatPace()` 配速格式化） |
| `stores/health-store.ts` | 健康数据 Zustand 状态（5 分钟缓存） |
| `stores/report-store.ts` | AI 报告 Zustand 状态（含下载状态） |
| `stores/llm-observe-store.ts` | LLM 观测 Zustand 状态（指标/Trace/建议） |
| `hooks/use-error-toast.ts` | 错误提示 Hook |

---

## utils.ts

```typescript
v(val: unknown): string | number    // null/undefined → '-'，否则原值
formatPace(paceMinPerKm): string    // 5.1 → 5'06" 跑步配速格式
```

**Why `v()` instead of `||`**: `val || '-'` 在值为 `0` 时错误显示 `-`，`v()` 仅在 `null`/`undefined` 时显示占位符。

---

## api.ts

### 接口

```typescript
api.getDashboard()                     // GET /dashboard
api.getReports(limit?)                 // GET /reports?limit=N
api.getReport(id)                      // GET /reports/:id
api.downloadReport(id): Promise<Blob>  // GET /reports/:id/download
api.triggerAnalyze()                   // POST /analyze
api.uploadHealth(data)                 // POST /v1/health/upload
api.getUsersSummary()                  // GET /users/summary
```

### 认证

```typescript
getAuthToken()   // localStorage('auth_token') || ''
setAuthToken(t)  // localStorage.setItem('auth_token', t)
```

### API 路径

```typescript
API_BASE  // /qm/api（Dashboard 端点）
V1_BASE   // /api（v1 端点，如 /api/v1/health/upload）
```

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
- `/src/components/layout/header.tsx` — 使用 stores
- `/src/app/dashboard/page.tsx` — 使用 health-store
- `/src/app/bigscreen/page.tsx` — 使用 health-store
- `/src/app/report/page.tsx` — 使用 report-store
- `/src/app/llm-observe/page.tsx` — 使用 llm-observe-store
