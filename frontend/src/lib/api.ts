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

  // /v1/* 走 V1_BASE(无 /qm/api 前缀),其他走 API_BASE
  const base = endpoint.startsWith('/v1/') ? V1_BASE : API_BASE;
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
