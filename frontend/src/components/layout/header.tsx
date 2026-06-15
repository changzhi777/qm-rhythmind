'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { getAuthToken } from '@/lib/api';

function getUserDisplay(): { avatar: string; name: string } {
  if (typeof window === 'undefined') return { avatar: '?', name: '' };
  const cached = localStorage.getItem('user_display');
  if (cached) {
    try { return JSON.parse(cached); } catch { /* ignore */ }
  }
  return { avatar: '?', name: getAuthToken() };
}

interface NavItem {
  href: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '仪表盘' },
  { href: '/bigscreen', label: '大屏' },
  { href: '/report', label: '报告' },
  { href: '/medical', label: '医疗' },
  { href: '/chat', label: 'Chat' },
  { href: '/upload', label: '上传' },
  { href: '/test-report', label: '测试' },
  { href: '/llm-observe', label: '观测' },
];

interface HeaderProps {
  title: string;
  activePath?: string;
  maxWidth?: string;
  showDate?: boolean;
  showBack?: boolean;
  extra?: React.ReactNode;
}

export function Header({ title, activePath, maxWidth = '1200px', showDate, showBack = true, extra }: HeaderProps) {
  const [mounted, setMounted] = useState(false);
  const router = useRouter();
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    return () => clearTimeout(t);
  }, []);

  const isHome = activePath === '/dashboard';

  return (
    <header className="border-b border-[var(--border)] px-6 py-4">
      <div className="flex items-center justify-between mx-auto" style={{ maxWidth }}>
        <div className="flex items-center gap-3">
          {showBack && !isHome && (
            <button
              onClick={() => router.back()}
              className="header-back-btn"
            >
              ‹ 返回
            </button>
          )}
          <div className="w-9 h-9 rounded-lg bg-[var(--primary)] flex items-center justify-center">
            <span className="text-white font-bold text-base">R</span>
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <Link href="/dashboard" className="text-lg font-semibold text-white no-underline">
                RHYTHMIND
              </Link>
              <span className="text-xs text-[var(--primary)] font-medium">律动</span>
              <span className="text-[11px] text-[var(--text-muted)] font-normal">v0.2.0</span>
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              {NAV_ITEMS.map((item, i) => (
                <span key={item.href}>
                  {i > 0 && ' · '}
                  <Link
                    href={item.href}
                    className={`text-xs no-underline ${activePath === item.href ? 'text-[var(--primary)] font-medium' : 'text-[var(--text-secondary)] font-normal'}`}
                  >
                    {item.label}
                  </Link>
                </span>
              ))}
              <span className="ml-2 text-[var(--text-muted)]">— {title}</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {showDate && mounted && (
            <span className="text-xs text-[var(--text-muted)]">
              {new Date().toLocaleDateString('zh-CN')}
            </span>
          )}
          {extra}
          {mounted && (() => {
            const display = getUserDisplay();
            return (
              <Link
                href="/"
                onClick={() => {
                  if (typeof window !== 'undefined') {
                    localStorage.removeItem('auth_token');
                    localStorage.removeItem('user_display');
                  }
                }}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-[var(--surface)] hover:bg-[var(--surface-elevated)] transition-colors no-underline"
              >
                <div className="header-user-avatar">
                  {display.avatar}
                </div>
                <span className="text-xs text-gray-300">{display.name}</span>
              </Link>
            );
          })()}
        </div>
      </div>
    </header>
  );
}
