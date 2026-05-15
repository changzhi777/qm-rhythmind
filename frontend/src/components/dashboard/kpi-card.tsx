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
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${statusColors[status]}`,
      borderRadius: '6px',
      padding: '12px 16px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{title}</span>
        {icon && <span style={{ fontSize: '14px' }}>{icon}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
        <span style={{ fontSize: '24px', fontWeight: '600', color: 'white' }}>{value}</span>
        {unit && <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{unit}</span>}
      </div>
    </div>
  );
}