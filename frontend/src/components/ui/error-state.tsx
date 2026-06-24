'use client';

// ErrorState 组件 — 错误占位 + 错误信息 + 重试按钮
// 2026-06-24 frontend-polish Stage 0

import type { ReactNode } from 'react';

interface ErrorStateProps {
  error?: Error | string | null;
  onRetry?: () => void;
  compact?: boolean;
  title?: string;
  action?: ReactNode;
}

function getMessage(error: Error | string | null | undefined): string {
  if (!error) return '发生未知错误';
  return typeof error === 'string' ? error : error.message || '发生未知错误';
}

export function ErrorState({
  error,
  onRetry,
  compact = false,
  title = '加载失败',
  action,
}: ErrorStateProps) {
  const message = getMessage(error);
  return (
    <div
      className={[
        'flex flex-col items-center justify-center text-center',
        compact ? 'py-6 px-4' : 'py-12 px-6',
      ].join(' ')}
      role="alert"
      aria-live="assertive"
    >
      <div
        className={[
          'flex items-center justify-center rounded-full bg-[var(--surface-elevated)] text-[var(--error)]',
          compact ? 'w-10 h-10 text-lg' : 'w-16 h-16 text-2xl',
        ].join(' ')}
        aria-hidden="true"
      >
        ⚠️
      </div>
      <h3 className={['font-medium text-[var(--foreground)] mb-1', compact ? 'text-sm mt-2' : 'text-base mt-4'].join(' ')}>
        {title}
      </h3>
      <p className="text-sm text-[var(--text-secondary)] max-w-md mb-3 break-words">{message}</p>
      <div className="flex items-center gap-2">
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="px-4 py-2 text-sm rounded-md bg-[var(--primary)] text-white hover:bg-[var(--secondary)] transition-colors"
          >
            🔄 重试
          </button>
        ) : null}
        {action}
      </div>
    </div>
  );
}