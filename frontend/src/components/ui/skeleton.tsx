// Skeleton 占位组件 — 用于 loading 状态

import type { CSSProperties } from 'react';

interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  borderRadius?: string;
  className?: string;
  style?: CSSProperties;
}

export function Skeleton({
  width = '100%',
  height = 16,
  borderRadius = '4px',
  className = '',
  style,
}: SkeletonProps) {
  return (
    <div
      className={`animate-pulse ${className}`}
      style={{
        width,
        height,
        background: 'var(--surface-elevated)',
        borderRadius,
        ...style,
      }}
    />
  );
}

interface SkeletonGroupProps {
  count: number;
  gap?: number;
  height?: number;
}

export function SkeletonGroup({ count, gap = 12, height = 80 }: SkeletonGroupProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap }}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} height={height} />
      ))}
    </div>
  );
}
