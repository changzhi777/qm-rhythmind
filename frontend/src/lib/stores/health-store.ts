// 健康数据状态管理

import { create } from 'zustand';
import { api } from '../api';
import type { HealthData } from '@/types/health';

interface HealthState {
  data: HealthData;
  loading: boolean;
  error: string | null;
  lastFetch: number | null;

  fetchDashboard: () => Promise<void>;
  clearData: () => void;
}

export const useHealthStore = create<HealthState>((set, get) => ({
  data: {} as HealthData,
  loading: false,
  error: null,
  lastFetch: null,

  fetchDashboard: async () => {
    // 5分钟内不重复请求
    const now = Date.now();
    if (get().lastFetch && now - get().lastFetch! < 5 * 60 * 1000) {
      return;
    }

    set({ loading: true, error: null });
    try {
      const response = await api.getDashboard();
      // Parse JSON string values in data
      const parsedData: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(response.data || {})) {
        if (typeof value === 'string' && value.startsWith('{')) {
          try {
            parsedData[key] = JSON.parse(value);
          } catch {
            parsedData[key] = value;
          }
        } else {
          parsedData[key] = value;
        }
      }
      set({
        data: parsedData as HealthData,
        loading: false,
        lastFetch: now,
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch dashboard',
        loading: false,
      });
    }
  },

  clearData: () => {
    set({ data: {} as HealthData, error: null, lastFetch: null });
  },
}));

// 选择器
export const selectProfile = (state: HealthState) => ({
  gender: state.data['profile.gender'],
  age: state.data['profile.age'],
  height_cm: state.data['profile.height_cm'],
  weight_kg: state.data['profile.weight_kg'],
  bmi: state.data['profile.bmi'],
  vo2_max: state.data['profile.vo2_max'],
  resting_hr: state.data['profile.resting_hr'],
  max_hr: state.data['profile.max_hr'],
});

export const selectTraining = (state: HealthState) => state.data['training.metrics'];
export const selectSleep = (state: HealthState) => state.data['sleep.summary'];
export const selectRunning = (state: HealthState) => state.data['running.summary'];
export const selectYearlyActivity = (state: HealthState) => state.data['activity_summary.yearly'];