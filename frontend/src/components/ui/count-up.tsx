'use client';

// CountUp 组件 — 数字 0→目标值平滑滚动(2026-06-24 v5)
// 用 requestAnimationFrame + ease-out cubic 实现

import { useEffect, useState } from 'react';

interface CountUpProps {
  value: number;
  duration?: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

export function CountUp({
  value,
  duration = 1200,
  decimals = 0,
  prefix = '',
  suffix = '',
  className = '',
}: CountUpProps) {
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    let startTime: number | null = null;
    const startValue = 0;
    let raf: number;

    const tick = (now: number) => {
      if (startTime === null) startTime = now;
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = startValue + (value - startValue) * eased;
      setCurrent(current);
      if (progress < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        setCurrent(value);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  const display =
    decimals > 0 ? current.toFixed(decimals) : Math.round(current).toString();

  return (
    <span className={className}>
      {prefix}
      {display}
      {suffix}
    </span>
  );
}