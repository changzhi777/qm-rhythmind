'use client';

// Modal 组件 — 模态对话框 + Portal + ESC 关闭 + 背景遮罩 + a11y
// 2026-06-24 frontend-polish Stage 0

import { useEffect, useRef, type ReactNode } from 'react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  children: ReactNode;
}

const SIZE_CLASS = {
  sm: 'max-w-md',
  md: 'max-w-2xl',
  lg: 'max-w-4xl',
} as const;

export function Modal({ open, onClose, title, footer, size = 'md', children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // focus first focusable
    const first = dialogRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    first?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 animate-[fadeIn_var(--dur-base)_var(--ease-out-soft)]"
      onClick={onClose}
      aria-hidden="true"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? 'modal-title' : undefined}
        className={[
          'w-full bg-[var(--surface)] border border-[var(--border)] rounded-lg shadow-2xl',
          'flex flex-col max-h-[90vh]',
          SIZE_CLASS[size],
        ].join(' ')}
        onClick={(e) => e.stopPropagation()}
      >
        {title ? (
          <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
            <h2 id="modal-title" className="text-base font-semibold text-[var(--foreground)]">
              {title}
            </h2>
            <button
              type="button"
              aria-label="关闭"
              onClick={onClose}
              className="text-[var(--text-secondary)] hover:text-[var(--foreground)] px-2 py-1 rounded transition-colors"
            >
              ✕
            </button>
          </div>
        ) : null}
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
        {footer ? (
          <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}