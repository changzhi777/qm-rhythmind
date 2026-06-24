'use client';

// Accordion 组件 — 手风琴展开/折叠(2026-06-24 v5)
// 用 grid-template-rows 1fr/0fr 平滑过渡

import { useState, type ReactNode } from 'react';

interface AccordionProps {
  title: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
  className?: string;
}

export function Accordion({
  title,
  defaultOpen = false,
  children,
  className = '',
}: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      className={`border border-[var(--border)] rounded-lg overflow-hidden ${className}`}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="
          w-full flex items-center justify-between
          px-4 py-3
          bg-[var(--surface-elevated)]/30
          hover:bg-[var(--surface-elevated)]/60
          transition-colors duration-[var(--dur-fast)]
          text-left
        "
        aria-expanded={open}
      >
        <span className="font-medium text-white text-sm">{title}</span>
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          className={`
            text-[var(--text-muted)]
            transition-transform duration-[var(--dur-base)]
            ease-[var(--ease-out-soft)]
            ${open ? 'rotate-180' : ''}
          `}
          aria-hidden="true"
        >
          <path
            d="M3 6l5 5 5-5"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <div
        className={`
          grid transition-[grid-template-rows]
          duration-[var(--dur-base)]
          ease-[var(--ease-out-soft)]
          ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}
        `}
      >
        <div className="overflow-hidden">
          <div className="px-4 py-3 text-sm text-[var(--text-secondary)]">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}