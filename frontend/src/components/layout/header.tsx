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
    <header style={{ borderBottom: '1px solid var(--border)', padding: '16px 24px' }}>
      <div style={{ maxWidth, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {showBack && !isHome && (
            <button
              onClick={() => router.back()}
              className="header-back-btn"
            >
              ‹ 返回
            </button>
          )}
          <div style={{
            width: '36px', height: '36px', borderRadius: '8px',
            background: 'var(--primary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ color: 'white', fontWeight: '700', fontSize: '16px' }}>R</span>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
              <Link href="/dashboard" style={{ fontSize: '18px', fontWeight: '600', color: 'white', textDecoration: 'none' }}>
                RHYTHMIND
              </Link>
              <span style={{ fontSize: '12px', color: 'var(--primary)', fontWeight: '500' }}>律动</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>v0.2.0</span>
            </div>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              {NAV_ITEMS.map((item, i) => (
                <span key={item.href}>
                  {i > 0 && ' · '}
                  <Link
                    href={item.href}
                    style={{
                      fontSize: '12px',
                      color: activePath === item.href ? 'var(--primary)' : 'var(--text-secondary)',
                      fontWeight: activePath === item.href ? '500' : '400',
                      textDecoration: 'none',
                    }}
                  >
                    {item.label}
                  </Link>
                </span>
              ))}
              <span style={{ marginLeft: '8px', color: 'var(--text-muted)' }}>— {title}</span>
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {showDate && mounted && (
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
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
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-[var(--surface)] hover:bg-[var(--surface-elevated)] transition-colors"
                style={{ textDecoration: 'none' }}
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
