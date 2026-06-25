// AI 报告状态管理

import { create } from 'zustand';
import { api } from '../api';
import type { Report } from '@/types/health';

interface ReportState {
  reports: Report[];
  currentReport: Report | null;
  loading: boolean;
  analyzing: boolean;
  downloading: boolean;
  ingesting: boolean;
  analyzeProgress: string;
  error: string | null;

  fetchReports: () => Promise<void>;
  fetchReport: (id: number) => Promise<void>;
  triggerAnalyze: () => Promise<void>;
  triggerAnalyzeWithSource: (params: {
    source: 'garmin_20260526' | 'upload' | 'url';
    files?: File[];
    url?: string;
  }) => Promise<void>;
  downloadReport: (id: number) => Promise<void>;
  clearCurrent: () => void;
}

export const useReportStore = create<ReportState>((set, get) => ({
  reports: [],
  currentReport: null,
  loading: false,
  analyzing: false,
  downloading: false,
  ingesting: false,
  analyzeProgress: '',
  error: null,

  fetchReports: async () => {
    set({ loading: true, error: null });
    try {
      const response = await api.getReports();
      set({ reports: response.reports || [], loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to fetch reports', loading: false });
    }
  },

  fetchReport: async (id) => {
    set({ loading: true, error: null });
    try {
      const response = await api.getReport(id);
      set({ currentReport: response.report, loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to fetch report', loading: false });
    }
  },

  triggerAnalyze: async () => {
    set({ analyzing: true, error: null });
    try {
      await api.triggerAnalyze();
      // 分析完成后刷新报告列表
      await get().fetchReports();
      set({ analyzing: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Analysis failed', analyzing: false });
    }
  },

  // 2026-06-25: 一链点动 - 数据源入库 + LLM 重新分析
  triggerAnalyzeWithSource: async (params) => {
    set({ ingesting: true, analyzing: true, error: null, analyzeProgress: '正在导入数据...' });
    try {
      const result = await api.analyzeWithSource(params);
      set({ ingesting: false, analyzeProgress: `已导入 ${result.ingested.facts_imported} 条数据,正在生成报告...` });
      // 刷新报告列表拿到新报告
      await get().fetchReports();
      // 选中最新报告
      if (result.report?.id) {
        await get().fetchReport(result.report.id);
      }
      set({ analyzing: false, analyzeProgress: '' });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Analyze failed',
        analyzing: false,
        ingesting: false,
        analyzeProgress: '',
      });
    }
  },

  downloadReport: async (id) => {
    const { downloading } = get();
    if (downloading) return;

    set({ downloading: true, error: null });
    try {
      const blob = await api.downloadReport(id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `RHYTHMIND-报告-${id}-${Date.now()}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (error) {
      set({ error: error instanceof Error ? error.message : '下载失败' });
    } finally {
      set({ downloading: false });
    }
  },

  clearCurrent: () => {
    set({ currentReport: null });
  },
}));
