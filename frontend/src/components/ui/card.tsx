'use client';

// Card 组件 — 统一容器 + 标题/页脚 + hover/click/selected 态
// 2026-06-24 frontend-polish Stage 0

import type { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title?: ReactNode;
  footer?: ReactNode;
  selected?: boolean;
  interactive?: boolean;
}

export function Card({
  title,
  footer,
  selected,
  interactive,
  className = '',
  children,
  ...rest
}: CardProps) {
  return (
    <div
      {...rest}
      className={[
        'bg-[var(--surface)] border rounded-md p-[var(--space-card)]',
        'transition-all duration-[var(--dur-fast)] ease-[var(--ease-out-soft)]',
        selected ? 'border-[var(--primary)]' : 'border-[var(--border)]',
        interactive ? 'cursor-pointer hover:bg-[var(--surface-elevated)] hover:border-[var(--text-muted)]' : '',
        className,
      ].join(' ')}
    >
      {title ? (
        <div className="text-sm font-medium text-[var(--text-secondary)] mb-3">{title}</div>
      ) : null}
      <div>{children}</div>
      {footer ? (
        <div className="mt-3 pt-3 border-t border-[var(--border)] text-xs text-[var(--text-muted)]">
          {footer}
        </div>
      ) : null}
    </div>
  );
}