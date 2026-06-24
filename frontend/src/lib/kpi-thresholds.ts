// KPI 5 状态阈值体系 — 2026-06-24 frontend-polish Stage 1.2
// Why: 替代硬编码 status,统一 excellent/good/average/concerned/danger 5 状态判定

export type KpiStatus = 'excellent' | 'good' | 'average' | 'concerned' | 'danger';

export interface ThresholdRange {
  excellent?: [number, number];
  good: [number, number];
  average?: [number, number];
  concerned?: [number, number];
  danger?: [number, number];
}

export interface ThresholdDef {
  /** 指标 key(用于查找) */
  key: string;
  /** 显示名 */
  label: string;
  /** 单位 */
  unit: string;
  /** 阈值区间 */
  ranges: ThresholdRange;
  /** 越高越好(true)还是越低越好(false) */
  higherIsBetter: boolean;
}

// 7 个核心指标默认阈值(从规格说明书同步)
export const DEFAULT_THRESHOLDS: Record<string, ThresholdDef> = {
  bmi: {
    key: 'bmi',
    label: 'BMI',
    unit: '',
    ranges: {
      excellent: [18.5, 22],
      good: [22, 24],
      average: [24, 26],
      concerned: [26, 28],
      danger: [28, 50],
    },
    higherIsBetter: false,
  },
  resting_hr: {
    key: 'resting_hr',
    label: '静息心率',
    unit: 'bpm',
    ranges: {
      excellent: [30, 60],
      good: [60, 65],
      average: [65, 70],
      concerned: [70, 80],
      danger: [80, 200],
    },
    higherIsBetter: false,
  },
  vo2_max: {
    key: 'vo2_max',
    label: 'VO2 Max',
    unit: 'ml/kg/min',
    ranges: {
      excellent: [50, 100],
      good: [40, 50],
      average: [30, 40],
      concerned: [20, 30],
      danger: [0, 20],
    },
    higherIsBetter: true,
  },
  readiness_score: {
    key: 'readiness_score',
    label: '训练准备度',
    unit: '/100',
    ranges: {
      excellent: [80, 100],
      good: [60, 80],
      average: [40, 60],
      concerned: [20, 40],
      danger: [0, 20],
    },
    higherIsBetter: true,
  },
  acwr: {
    key: 'acwr',
    label: 'ACWR',
    unit: '',
    ranges: {
      excellent: [0.8, 1.3],
      good: [0.6, 0.8],
      average: [0.0, 0.6],
      concerned: [1.3, 1.5],
      danger: [1.5, 3.0],
    },
    higherIsBetter: false,
  },
  deep_sleep_pct: {
    key: 'deep_sleep_pct',
    label: '深睡占比',
    unit: '%',
    ranges: {
      excellent: [25, 100],
      good: [20, 25],
      average: [15, 20],
      concerned: [10, 15],
      danger: [0, 10],
    },
    higherIsBetter: true,
  },
};

/**
 * 根据数值 + 阈值定义返回 5 状态之一
 */
// 优化 #7:模块级 inRange,消除闭包分配
const inRange = (v: number, r?: [number, number]): boolean =>
  r ? v >= r[0] && v < r[1] : false;

export function evaluateKpi(value: number | undefined | null, def: ThresholdDef): KpiStatus | null {
  if (value == null || Number.isNaN(value)) return null;
  const r = def.ranges;
  if (inRange(value, r.excellent)) return 'excellent';
  if (inRange(value, r.good)) return 'good';
  if (inRange(value, r.average)) return 'average';
  if (inRange(value, r.concerned)) return 'concerned';
  if (inRange(value, r.danger)) return 'danger';
  // 超出所有已知范围 → 根据方向推断
  if (def.higherIsBetter) return value > (r.excellent?.[1] ?? Infinity) ? 'excellent' : 'danger';
  return value < (r.excellent?.[0] ?? -Infinity) ? 'danger' : 'excellent';
}

// 优化 #4:统一 localStorage 工具函数,消除 4 处 SSR guard + try/catch 重复
function safeStorageGet<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function safeStorageSet(key: string, value: unknown): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

const THRESHOLD_STORAGE_KEY = 'rhythmind.kpi.thresholds.v1';

export function loadThresholdOverrides(): Record<string, Partial<ThresholdRange>> {
  return safeStorageGet<Record<string, Partial<ThresholdRange>>>(THRESHOLD_STORAGE_KEY, {});
}

export function saveThresholdOverrides(overrides: Record<string, Partial<ThresholdRange>>): void {
  safeStorageSet(THRESHOLD_STORAGE_KEY, overrides);
}

export function applyOverrides(base: Record<string, ThresholdDef>, overrides: Record<string, Partial<ThresholdRange>>): Record<string, ThresholdDef> {
  const out: Record<string, ThresholdDef> = { ...base };
  for (const [key, ov] of Object.entries(overrides)) {
    if (out[key] && ov) {
      out[key] = { ...out[key], ranges: { ...out[key].ranges, ...ov } };
    }
  }
  return out;
}

// Stage 1.4: 用户目标 + 进度环
export interface Goal {
  metric: string; // 'profile.vo2_max' | 'profile.weight_kg' | ...
  target: number;
  deadline?: string; // ISO date
  createdAt: string;
}

const GOALS_STORAGE_KEY = 'rhythmind.goals.v1';

export function loadGoals(): Goal[] {
  return safeStorageGet<Goal[]>(GOALS_STORAGE_KEY, []);
}

export function saveGoals(goals: Goal[]): void {
  safeStorageSet(GOALS_STORAGE_KEY, goals);
}

export function addGoal(goal: Omit<Goal, 'createdAt'>): Goal {
  const goals = loadGoals();
  const newGoal: Goal = { ...goal, createdAt: new Date().toISOString() };
  saveGoals([...goals.filter((g) => g.metric !== goal.metric), newGoal]);
  return newGoal;
}

export function getGoalFor(metric: string, goals: Goal[]): Goal | undefined {
  return goals.find((g) => g.metric === metric);
}

/** 计算进度 0-1(支持 higher/lower is better) */
export function calcProgress(current: number | undefined, goal: Goal, higherIsBetter: boolean): number | null {
  if (current == null || Number.isNaN(current)) return null;
  // 简化进度算法:基于与目标的差距
  const diff = current - goal.target;
  if (higherIsBetter) {
    // 当前 ≥ 目标 = 100%
    if (diff >= 0) return 1;
    return Math.max(0, 1 + diff / Math.abs(goal.target || 1));
  } else {
    // 当前 ≤ 目标 = 100%(如体重)
    if (diff <= 0) return 1;
    return Math.max(0, 1 - diff / Math.abs(goal.target || 1));
  }
}