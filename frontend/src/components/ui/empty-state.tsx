'use client';

// EmptyState 组件 — 空数据占位 + 图标 + 标题 + 描述 + CTA
// 2026-06-24 frontend-polish Stage 0

import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({
  icon,
  title = '暂无数据',
  description,
  action,
}: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center justify-center text-center py-12 px-6"
      role="status"
      aria-live="polite"
    >
      <div
        className="w-16 h-16 mb-4 flex items-center justify-center rounded-full bg-[var(--surface-elevated)] text-2xl text-[var(--text-muted)]"
        aria-hidden="true"
      >
        {icon ?? '📋'}
      </div>
      <h3 className="text-base font-medium text-[var(--foreground)] mb-2">{title}</h3>
      {description ? (
        <div className="text-sm text-[var(--text-secondary)] max-w-md mb-4">{description}</div>
      ) : null}
      {action ? <div>{action}</div> : null}
    </div>
  );
}