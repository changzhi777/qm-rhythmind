// UI 组件统一导出 — 8 组件库
// 2026-06-24 frontend-polish Stage 0

export { Button, type ButtonVariant, type ButtonSize } from './button';
export { Card } from './card';
export { EmptyState } from './empty-state';
export { ErrorState } from './error-state';
export { Modal } from './modal';
export { Skeleton, SkeletonGroup } from './skeleton';
export { Sparkline } from './sparkline';
export { Tabs, type TabItem } from './tabs';
export { Toast } from './toast'; // legacy 单 toast(已存在)
export { ToastHost } from './toast-host'; // 新版多 toast 队列

// Store 导出
export { useGlobalStore, useToast, useConfirm } from '@/lib/stores/global-store';
export type { ToastType, ToastItem, ModalConfig } from '@/lib/stores/global-store';