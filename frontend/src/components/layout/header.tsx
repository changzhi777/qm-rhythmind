'use client';

import Link from 'next/link';
import { useState } from 'react';

interface NavItem {
  href: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/dashboard', label: '仪表盘' },
  { href: '/bigscreen', label: '大屏' },
  { href: '/report', label: '报告' },
];

interface HeaderProps {
  title: string;
  activePath?: string;
  maxWidth?: string;
  showDate?: boolean;
  extra?: React.ReactNode;
}

export function Header({ title, activePath, maxWidth = '1200px', showDate, extra }: HeaderProps) {
  const [mounted] = useState(false);
  return (
    <header style={{ borderBottom: '1px solid var(--border)', padding: '16px 24px' }}>
      <div style={{ maxWidth, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
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
          {showDate && (
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {mounted ? new Date().toLocaleDateString('zh-CN') : ''}
            </span>
          )}
          {extra}
        </div>
      </div>
    </header>
  );
}
