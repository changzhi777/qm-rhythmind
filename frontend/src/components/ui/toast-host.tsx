'use client';

// ToastHost — 全局 Toast 容器,支持多 toast 队列 + 4 类型 + 自动关闭
// 2026-06-24 frontend-polish Stage 0 + 优化 #15

import { useGlobalStore, type ToastType } from '@/lib/stores/global-store';

const TYPE_STYLES: Record<ToastType, string> = {
  info: 'bg-[var(--info)] text-black',
  success: 'bg-[var(--status-good)] text-black',
  warning: 'bg-[var(--status-concerned)] text-black',
  error: 'bg-[var(--error)] text-white',
};

const TYPE_ICONS: Record<ToastType, string> = {
  info: 'ℹ️',
  success: '✅',
  warning: '⚠️',
  error: '❌',
};

export function ToastHost() {
  const toasts = useGlobalStore((s) => s.toasts);
  const remove = useGlobalStore((s) => s.removeToast);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 max-w-sm"
      role="region"
      aria-label="通知"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => remove(t.id)}
          className={[
            TYPE_STYLES[t.type],
            'flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg',
            'cursor-pointer hover:opacity-90 transition-opacity',
            'animate-[slideInRight_var(--dur-base)_var(--ease-out-soft)]',
            'text-left text-sm',
          ].join(' ')}
        >
          <span aria-hidden="true">{TYPE_ICONS[t.type]}</span>
          <span className="flex-1 break-words">{t.message}</span>
        </button>
      ))}
    </div>
  );
}