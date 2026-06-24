// KPI 卡片 — 扁平 + 5 状态色板(2026-06-24 frontend-polish Stage 1.2)

import type { ReactNode } from 'react';

type KpiStatus = 'excellent' | 'good' | 'average' | 'concerned' | 'danger';

interface KpiCardProps {
  title: string;
  value: string | number;
  unit?: string;
  status?: KpiStatus;
  icon?: ReactNode;
}

const STATUS_BORDER: Record<KpiStatus, string> = {
  excellent: 'border-l-[var(--status-excellent)]',
  good: 'border-l-[var(--status-good)]',
  average: 'border-l-[var(--status-average)]',
  concerned: 'border-l-[var(--status-concerned)]',
  danger: 'border-l-[var(--status-danger)]',
};

export function KpiCard({ title, value, unit, status = 'good', icon }: KpiCardProps) {
  return (
    <div
      className={[
        'bg-[var(--surface)] border border-[var(--border)] border-l-[3px] rounded-md px-4 py-3',
        'transition-colors duration-[var(--dur-fast)]',
        STATUS_BORDER[status],
      ].join(' ')}
    >
      <div className="flex justify-between items-start mb-2">
        <span className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider">{title}</span>
        {icon ? <span className="text-sm">{icon}</span> : null}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-semibold text-white">{value}</span>
        {unit ? <span className="text-xs text-[var(--text-muted)]">{unit}</span> : null}
      </div>
    </div>
  );
}