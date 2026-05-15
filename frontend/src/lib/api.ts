// RHYTHMIND API 调用层

import type { Report } from '@/types/health';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8888/qm';

interface ApiResponse<T> {
  status: string;
  data?: T;
  error?: string;
}

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

function getAuthToken(): string {
  if (typeof window === 'undefined') return 'garmin_user_001';
  return localStorage.getItem('auth_token') || 'garmin_user_001';
}

export async function fetchWithAuth<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const token = getAuthToken();

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      ...options?.headers,
    },
  });

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
};