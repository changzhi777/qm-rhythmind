import { create } from "zustand";
import { API_BASE, getAuthToken } from "../api";

// ── Types ──────────────────────────────────────────────────────────────

interface MetricByModel {
  model: string;
  calls: number;
  avg_latency_ms: number;
  tokens: number;
  cost: number;
}

interface MetricByDay {
  date: string;
  calls: number;
  avg_latency_ms: number;
  tokens: number;
  cost: number;
}

interface LLMMetrics {
  total_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  total_tokens: number;
  total_cost: number;
  by_model: MetricByModel[];
  by_day: MetricByDay[];
}

interface TraceItem {
  id: string;
  name: string;
  user_id: string | null;
  model: string | null;
  status: string;
  latency_ms: number | null;
  tokens: number;
  cost: number;
  created_at: string;
}

interface Suggestion {
  title: string;
  severity: "info" | "warn" | "critical";
  detail: string;
  metric_key: string;
  current_value: number;
  threshold: number;
}

// ── Store ──────────────────────────────────────────────────────────────

interface LLMObserveState {
  metrics: LLMMetrics | null;
  traces: TraceItem[];
  suggestions: Suggestion[];
  analysisReport: string;
  loading: boolean;
  error: string | null;
  fetchMetrics: (days?: number) => Promise<void>;
  fetchTraces: (limit?: number, offset?: number) => Promise<void>;
  fetchSuggestions: (days?: number) => Promise<void>;
  runAnalysis: (days?: number) => Promise<void>;
}

export const useLLMObserveStore = create<LLMObserveState>((set) => ({
  metrics: null,
  traces: [],
  suggestions: [],
  analysisReport: "",
  loading: false,
  error: null,

  fetchMetrics: async (days = 7) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(
        `${API_BASE}/v1/llm-observe/metrics?days=${days}`,
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      set({ metrics: await res.json() });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  fetchTraces: async (limit = 50, offset = 0) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(
        `${API_BASE}/v1/llm-observe/traces?limit=${limit}&offset=${offset}`,
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      set({ traces: await res.json() });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  fetchSuggestions: async (days = 7) => {
    set({ loading: true, error: null });
    try {
      const res = await fetch(
        `${API_BASE}/v1/llm-observe/suggestions?days=${days}`,
        { headers: { Authorization: `Bearer ${getAuthToken()}` } }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      set({ suggestions: data.suggestions });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },

  runAnalysis: async (days = 7) => {
    set({ loading: true, error: null, analysisReport: "" });
    try {
      const res = await fetch(`${API_BASE}/v1/llm-observe/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${getAuthToken()}`,
        },
        body: JSON.stringify({ days }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      set({ analysisReport: data.report });
    } catch (e: unknown) {
      set({ error: (e as Error).message });
    } finally {
      set({ loading: false });
    }
  },
}));
