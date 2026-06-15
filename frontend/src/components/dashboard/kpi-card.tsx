// KPI 卡片 — 扁平无装饰

import type { ReactNode } from 'react';

interface KpiCardProps {
  title: string;
  value: string | number;
  unit?: string;
  status?: 'excellent' | 'good' | 'warning' | 'danger';
  icon?: ReactNode;
}

export function KpiCard({ title, value, unit, status = 'good', icon }: KpiCardProps) {
  const statusColors = {
    excellent: 'var(--success)',
    good: 'var(--info)',
    warning: 'var(--warning)',
    danger: 'var(--error)',
  };

  return (
    <div
      className="bg-[var(--surface)] border border-[var(--border)] rounded-md px-4 py-3"
      style={{ borderLeft: `3px solid ${statusColors[status]}` }}
    >
      <div className="flex justify-between items-start mb-2">
        <span className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider">{title}</span>
        {icon && <span className="text-sm">{icon}</span>}
      </div>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-semibold text-white">{value}</span>
        {unit && <span className="text-xs text-[var(--text-muted)]">{unit}</span>}
      </div>
    </div>
  );
}