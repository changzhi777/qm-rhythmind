'use client';

// Button 组件 — 4 变体(primary / secondary / danger / ghost)+ loading + 尺寸
// 2026-06-24 frontend-polish Stage 0

import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: ReactNode;
}

const VARIANT_STYLES: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--primary)] text-white hover:bg-[var(--secondary)] active:scale-[0.98]',
  secondary:
    'bg-transparent border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--surface-elevated)]',
  danger:
    'bg-[var(--error)] text-white hover:opacity-90 active:scale-[0.98]',
  ghost:
    'bg-transparent text-[var(--text-secondary)] hover:text-[var(--foreground)] hover:bg-[var(--surface-elevated)]',
};

const SIZE_STYLES: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-6 py-3 text-base',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  leftIcon,
  disabled,
  className = '',
  children,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <button
      {...rest}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={[
        'inline-flex items-center justify-center gap-2 rounded-md font-medium',
        'transition-all duration-[var(--dur-fast)] ease-[var(--ease-out-soft)]',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        VARIANT_STYLES[variant],
        SIZE_STYLES[size],
        className,
      ].join(' ')}
    >
      {loading ? (
        <span
          className="inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"
          aria-hidden="true"
        />
      ) : leftIcon ? (
        <span aria-hidden="true">{leftIcon}</span>
      ) : null}
      {children}
    </button>
  );
}