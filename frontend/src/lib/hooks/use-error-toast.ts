// 全局错误 Toast Hook

import { create } from 'zustand';

interface ToastState {
  message: string | null;
  type: 'error' | 'success' | 'info';
  show: (message: string, type?: 'error' | 'success' | 'info') => void;
  hide: () => void;
}

export const useToastStore = create<ToastState>((set) => ({
  message: null,
  type: 'error',
  show: (message, type = 'error') => set({ message, type }),
  hide: () => set({ message: null }),
}));

export function useErrorToast() {
  const { show, hide } = useToastStore();

  const error = (message: string) => {
    show(message, 'error');
    setTimeout(hide, 3000);
  };

  const success = (message: string) => {
    show(message, 'success');
    setTimeout(hide, 3000);
  };

  return { error, success, hide };
}
