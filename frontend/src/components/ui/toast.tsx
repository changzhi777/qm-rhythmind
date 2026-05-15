'use client';

import { useToastStore } from '@/lib/hooks/use-error-toast';

const typeStyles = {
  error: 'bg-[var(--error)]',
  success: 'bg-[var(--success)]',
  info: 'bg-[var(--info)]',
};

export function Toast() {
  const { message, type, hide } = useToastStore();

  if (!message) return null;

  return (
    <div
      className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-2 fade-in duration-200"
      onClick={hide}
    >
      <div className={`${typeStyles[type]} text-white px-6 py-3 rounded-xl shadow-lg cursor-pointer`}>
        {message}
      </div>
    </div>
  );
}
