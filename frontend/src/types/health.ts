// 类型定义

export interface Profile {
  gender?: string;
  age?: number;
  height_cm?: number;
  weight_kg?: number;
  bmi?: number;
  vo2_max?: number;
  resting_hr?: number;
  max_hr?: number;
  hr_zones?: Record<string, [number, number]>;
}

export interface TrainingMetrics {
  endurance_score?: number;
  endurance_class?: string;
  acwr?: number;
  acwr_status?: string;
  readiness_score?: number;
  hill_score?: number;
  race_predictions?: Record<string, number>;
}

export interface RunningSummary {
  avg_pace_min_per_km?: number;
  total_km?: number;
  total_runs?: number;
}

export interface SleepSummary {
  avg_total_hours?: number;
  deep_pct?: number;
  avg_deep_hours?: number;
  avg_rem_hours?: number;
  record_days?: number;
}

export interface ActivityYearly {
  distance: number;
  count: number;
}

export interface HealthData {
  'profile.gender'?: string;
  'profile.age'?: number;
  'profile.height_cm'?: number;
  'profile.weight_kg'?: number;
  'profile.bmi'?: number;
  'profile.vo2_max'?: number;
  'profile.resting_hr'?: number;
  'profile.max_hr'?: number;
  'training.metrics'?: TrainingMetrics;
  'running.summary'?: RunningSummary;
  'sleep.summary'?: SleepSummary;
  'activity_summary.yearly'?: Record<string, ActivityYearly>;
}

export interface Report {
  id: number;
  content: string;
  model: string;
  timestamp: string;
  is_current?: boolean;
}

export interface KpiData {
  title: string;
  value: string | number;
  unit?: string;
  trend?: 'up' | 'down' | 'stable';
  status?: 'excellent' | 'good' | 'warning' | 'danger';
}