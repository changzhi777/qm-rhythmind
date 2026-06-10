// useAutoRefresh Hook — 定时触发刷新

import { useEffect, useRef } from 'react';

export function useAutoRefresh(
  intervalMs: number,
  callback: () => void | Promise<void>,
  enabled: boolean = true,
): void {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => {
      void savedCallback.current();
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
}
