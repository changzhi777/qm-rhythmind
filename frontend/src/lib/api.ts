// RHYTHMIND API 调用层

import type { Report } from '@/types/health';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/qm/api';
// /api/v1/* 端点的实际路径（去掉 /qm 前缀）
const V1_BASE = API_BASE.replace('/qm/api', '/api');

interface ReportsResponse {
  status: string;
  reports: Report[];
}

interface SingleReportResponse {
  status: string;
  report: Report;
}

interface AnalyzeResponse {
  status: string;
  message: string;
  chars: number;
}

interface UploadResponse {
  status: string;
}

interface UserSummary {
  user_id: string;
  display_name: string;
  avatar: string;
  facts_count: number;
  has_medical: boolean;
  profile: {
    age?: number;
    gender?: string;
    vo2_max?: number;
    bmi?: number;
  };
  running?: {
    total_runs?: number;
    total_km?: number;
    avg_pace_min_per_km?: number;
  };
  active_medications?: number;
  abnormal_labs?: number;
}

interface UsersSummaryResponse {
  status: string;
  users: UserSummary[];
}

export interface InfluxDataPoint {
  ts: string;       // ISO 8601 timestamp
  value: number;
}

export interface InfluxTimeSeriesResponse {
  status: 'ok' | 'degraded';
  metric: string;
  range: string;
  aggregation: string;
  fn: string;
  data: InfluxDataPoint[];
  count: number;
  latest: number | null;
  avg: number | null;
  error?: string;
}

export function getAuthToken(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem('auth_token') || '';
}

export function setAuthToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem('auth_token', token);
}

export { API_BASE, V1_BASE };
export type { UserSummary, UsersSummaryResponse };

// ── Persona 类型(2026-06-24) ─────────────────────────────────────────
export interface PersonaGoal {
  metric: string;
  target: number;
  unit?: string;
  deadline?: string;
}

export interface Persona {
  title: string;
  summary: string;
  background?: string;
  strengths?: string[];
  concerns?: string[];
  goals?: PersonaGoal[];
}

export interface PersonaResponse {
  user_id: string;
  persona: Persona | null;
  has_persona: boolean;
}

export async function fetchWithAuth<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const token = getAuthToken();

  // 2026-06-25: 后端有两套前缀:
  //   - dashboard.py 显式 prefix="/qm/api" → 走 API_BASE ("/qm/api")
  //   - health/medical/llm-observe/feishu/privacy/auth 在 main.py 挂 prefix="/api/v1" → 走 V1_BASE ("/api")
  // 前端 basePath=/qm,统一从 API_BASE 出发会把 /v1/* 拼成 /qm/api/v1/* → 404
  // 解法:/v1/* 路径走 V1_BASE(nginx 已在代理 /api/*),其余走 API_BASE
  const isV1 = endpoint.startsWith('/v1/');
  const base = isV1 ? V1_BASE : API_BASE;
  const res = await fetch(`${base}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options?.headers,
    },
  });

  // 401 → 强制退出登录并跳回首页
  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('user_display');
      window.location.href = '/';
    }
    throw new Error('Unauthorized: token expired or invalid');
  }

  if (!res.ok) {
    throw new Error(`API Error: ${res.status} ${res.statusText}`);
  }

  return res.json();
}

export const api = {
  getDashboard() {
    return fetchWithAuth<{ status: string; data: Record<string, unknown> }>('/dashboard');
  },

  getReports(limit = 20) {
    return fetchWithAuth<ReportsResponse>(`/reports?limit=${limit}`);
  },

  getReport(id: number) {
    return fetchWithAuth<SingleReportResponse>(`/reports/${id}`);
  },

  downloadReport(id: number): Promise<Blob> {
    const token = getAuthToken();
    return fetch(`${API_BASE}/reports/${id}/download`, {
      headers: { 'Authorization': `Bearer ${token}` },
    }).then(res => {
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);
      return res.blob();
    });
  },

  triggerAnalyze() {
    return fetchWithAuth<AnalyzeResponse>('/analyze', { method: 'POST' });
  },

  uploadHealth(data: Record<string, unknown>) {
    return fetchWithAuth<UploadResponse>('/v1/health/upload', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getUsersSummary() {
    return fetchWithAuth<UsersSummaryResponse>('/users/summary');
  },

  // 2026-06-25: 直接 LLM 对话（调 oMLX 算力后台，绕过工作流路由）
  // POST /api/v1/llm/chat → { reply, model, latency_ms }
  chatWithLLM(
    message: string,
    history: Array<{ role: 'user' | 'assistant'; content: string }> = [],
    options: { temperature?: number; max_tokens?: number } = {},
  ) {
    return fetchWithAuth<{
      reply: string;
      model: string;
      latency_ms: number;
      usage?: Record<string, number>;
    }>('/v1/llm/chat', {
      method: 'POST',
      body: JSON.stringify({
        message,
        history,
        temperature: options.temperature ?? 0.7,
        max_tokens: options.max_tokens ?? 1024,
      }),
    });
  },

  // v6: 登录换 JWT(解决点击卡片 401 重定向问题)
  // 注意:login 端点在 /api/v1/* 前缀(由 /api/v1/auth 路由提供)
  async login(userId: string): Promise<{ access_token: string; expires_in: number }> {
    const res = await fetch(`${V1_BASE}/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    if (!res.ok) {
      throw new Error(`Login failed: ${res.status}`);
    }
    const data = (await res.json()) as { access_token: string; expires_in: number };
    // 自动用返回的 JWT 替换 dev token
    if (typeof window !== 'undefined' && data.access_token) {
      localStorage.setItem('auth_token', data.access_token);
    }
    return data;
  },

  getUserPersona(userId: string) {
    // persona 端点在 /api/v1/(由 dashboard_ext.py 提供,无 /qm/api 前缀)
    return fetchWithAuth<PersonaResponse>(`/v1/users/${userId}/persona`);
  },

  getInfluxTimeSeries(
    metric: string,
    range: string = '-7d',
    aggregation: string = '1d',
    fn: string = 'mean',
  ): Promise<InfluxTimeSeriesResponse> {
    const params = new URLSearchParams({ metric, range, aggregation, fn });
    return fetchWithAuth<InfluxTimeSeriesResponse>(`/influxdb/timeseries?${params}`);
  },
};
