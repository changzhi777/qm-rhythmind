'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

interface NavItem {
  href: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '仪表盘' },
  { href: '/bigscreen', label: '大屏' },
  { href: '/report', label: '报告' },
  { href: '/chat', label: 'Chat' },
  { href: '/upload', label: '上传' },
  { href: '/test-report', label: '测试' },
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
  useEffect(() => { setMounted(true); }, []);

  const isHome = activePath === '/dashboard';

  return (
    <header style={{ borderBottom: '1px solid var(--border)', padding: '16px 24px' }}>
      <div style={{ maxWidth, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {showBack && !isHome && (
            <button
              onClick={() => router.back()}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text-secondary)', fontSize: '14px', padding: '4px 8px',
                borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '4px',
              }}
              onMouseOver={e => e.currentTarget.style.color = 'var(--primary)'}
              onMouseOut={e => e.currentTarget.style.color = 'var(--text-secondary)'}
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
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>v0.1.9</span>
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
        </div>
      </div>
    </header>
  );
}
