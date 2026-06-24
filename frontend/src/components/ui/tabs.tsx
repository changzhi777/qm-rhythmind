'use client';

// Tabs 组件 — 标签页 + 激活态 + a11y(role=tab / aria-selected)+ 键盘可达
// 2026-06-24 frontend-polish Stage 0

import { useId } from 'react';

export interface TabItem {
  key: string;
  label: string;
  badge?: number | string;
}

interface TabsProps {
  tabs: TabItem[];
  active: string;
  onChange: (key: string) => void;
  className?: string;
}

export function Tabs({ tabs, active, onChange, className = '' }: TabsProps) {
  const baseId = useId();
  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      className={['flex gap-1 border-b border-[var(--border)] overflow-x-auto', className].join(' ')}
    >
      {tabs.map((t, idx) => {
        const selected = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`${baseId}-tab-${t.key}`}
            aria-selected={selected}
            aria-controls={`${baseId}-panel-${t.key}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.key)}
            // 优化 #8:O(n) findIndex → 闭包索引
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') {
                e.preventDefault();
                onChange(tabs[(idx + 1) % tabs.length].key);
              } else if (e.key === 'ArrowLeft') {
                e.preventDefault();
                onChange(tabs[(idx - 1 + tabs.length) % tabs.length].key);
              }
            }}
            className={[
              'relative px-4 py-2.5 text-sm font-medium whitespace-nowrap',
              'transition-colors duration-[var(--dur-fast)]',
              'border-b-2 -mb-px',
              selected
                ? 'text-[var(--primary)] border-[var(--primary)]'
                : 'text-[var(--text-secondary)] border-transparent hover:text-[var(--foreground)]',
            ].join(' ')}
          >
            {t.label}
            {t.badge !== undefined ? (
              <span
                className={[
                  'ml-2 inline-flex items-center justify-center text-xs px-1.5 rounded-full',
                  selected ? 'bg-[var(--primary)] text-white' : 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]',
                ].join(' ')}
              >
                {t.badge}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}