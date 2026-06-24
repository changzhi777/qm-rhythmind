'use client';

// Global Store — 全局 Toast 队列 + Modal + Sidebar
// 2026-06-24 frontend-polish Stage 0 + 优化(#1 #2 #16)

import { create } from 'zustand';

export type ToastType = 'info' | 'success' | 'warning' | 'error';

export interface ToastItem {
  id: string;
  type: ToastType;
  message: string;
  duration: number; // ms; 0 = 不自动关闭
}

export interface ModalConfig {
  title?: string;
  content: string;
  onConfirm?: () => void;
  onCancel?: () => void;
  confirmText?: string;
  cancelText?: string;
  variant?: 'default' | 'danger';
}

interface GlobalState {
  toasts: ToastItem[];
  pushToast: (toast: Omit<ToastItem, 'id'> & { id?: string }) => string;
  removeToast: (id: string) => void;
  clearToasts: () => void;

  modal: ModalConfig | null;
  openModal: (config: ModalConfig) => void;
  closeModal: () => void;

  sidebarOpen: boolean;
  setSidebar: (open: boolean) => void;
}

const genId = (): string => {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `t_${crypto.randomUUID()}`;
  }
  return `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
};

export const useGlobalStore = create<GlobalState>((set, get) => ({
  toasts: [],
  pushToast: ({ type = 'info', message, duration = 3000, id }) => {
    const finalId = id ?? genId();
    const item: ToastItem = { id: finalId, type, message, duration };
    set((s) => ({ toasts: [...s.toasts, item] }));
    if (duration > 0) {
      setTimeout(() => get().removeToast(finalId), duration);
    }
    return finalId;
  },
  removeToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clearToasts: () => set({ toasts: [] }),

  modal: null,
  openModal: (config) => set({ modal: config }),
  closeModal: () => set({ modal: null }),

  sidebarOpen: false,
  setSidebar: (open) => set({ sidebarOpen: open }),
}));

/** 便捷 hook:吐司 */
export function useToast() {
  const push = useGlobalStore((s) => s.pushToast);
  const remove = useGlobalStore((s) => s.removeToast);
  return {
    info: (message: string, duration = 3000) => push({ type: 'info', message, duration }),
    success: (message: string, duration = 3000) => push({ type: 'success', message, duration }),
    warning: (message: string, duration = 4000) => push({ type: 'warning', message, duration }),
    error: (message: string, duration = 5000) => push({ type: 'error', message, duration }),
    dismiss: remove,
  };
}

/** 便捷 hook:全局确认弹窗(优化 #1:消除内存泄漏 + 二次 resolve)*/
export function useConfirm() {
  const openModal = useGlobalStore((s) => s.openModal);
  const closeModal = useGlobalStore((s) => s.closeModal);
  return {
    confirm: (config: Omit<ModalConfig, 'onConfirm' | 'onCancel'>): Promise<boolean> =>
      new Promise((resolve) => {
        let resolved = false;
        const settle = (value: boolean) => {
          if (resolved) return;
          resolved = true;
          resolve(value);
        };
        openModal({
          ...config,
          onConfirm: () => {
            closeModal();
            settle(true);
          },
          onCancel: () => {
            closeModal();
            settle(false);
          },
        });
      }),
    close: closeModal,
  };
}