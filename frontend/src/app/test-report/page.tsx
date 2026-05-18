'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Header } from '@/components/layout/header';

interface TestReport {
  id: string;
  timestamp: string;
  rounds: number;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  page_avg_ms: number;
  api_avg_ms: number;
  files: { name: string; url: string; size_kb: number; type: string }[];
}

export default function TestReportPage() {
  const [reports, setReports] = useState<TestReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchReports() {
      try {
        const token = typeof window !== 'undefined'
          ? localStorage.getItem('auth_token') || 'garmin_user_001'
          : 'garmin_user_001';
        const res = await fetch('/qm/api/test-reports', {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setReports(data.reports || []);
      } catch (e) {
        setError(e instanceof Error ? e.message : '获取报告失败');
      } finally {
        setLoading(false);
      }
    }
    fetchReports();
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header title="测试报告" activePath="/test-report" maxWidth="1200px" />

      <main style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
        <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>E2E 测试报告列表</h2>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)' }}>加载中...</div>
        ) : error ? (
          <div className="card" style={{ textAlign: 'center', padding: '48px' }}>
            <div style={{ fontSize: '32px', marginBottom: '8px' }}>⚠️</div>
            <p style={{ color: 'var(--error)', fontSize: '13px' }}>{error}</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: '8px' }}>提示：通过 <code style={{ background: 'var(--surface-elevated)', padding: '2px 6px', borderRadius: '4px' }}>python3 tests/e2e_test.py --upload</code> 生成并上传报告</p>
          </div>
        ) : reports.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: '48px' }}>
            <div style={{ fontSize: '32px', marginBottom: '8px' }}>📋</div>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>暂无测试报告</p>
            <p style={{ color: 'var(--text-muted)', fontSize: '12px', marginTop: '8px' }}>运行 <code style={{ background: 'var(--surface-elevated)', padding: '2px 6px', borderRadius: '4px' }}>python3 tests/e2e_test.py --upload</code> 生成并上传报告到服务器</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {reports.map((report) => (
              <div key={report.id} className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                      <h3 style={{ fontSize: '15px', fontWeight: '600', color: 'white' }}>
                        {report.timestamp.replace('T', ' ').substring(0, 19)}
                      </h3>
                      <span style={{
                        fontSize: '10px', padding: '2px 8px', borderRadius: '4px',
                        background: report.pass_rate === 100 ? 'var(--success)' : 'var(--warning)',
                        color: 'white', fontWeight: '500',
                      }}>
                        {report.pass_rate.toFixed(1)}%
                      </span>
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {report.rounds} 轮 · {report.passed}/{report.total} 通过 · 页面 {report.page_avg_ms}ms · API {report.api_avg_ms}ms
                    </p>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '8px' }}>
                  {report.files.map((file) => (
                    <a
                      key={file.name}
                      href={file.url}
                      download
                      className="card"
                      style={{
                        display: 'flex', alignItems: 'center', gap: '8px',
                        textDecoration: 'none', padding: '10px 12px',
                        background: 'var(--surface-elevated)',
                        cursor: 'pointer',
                      }}
                    >
                      <FileIcon type={file.type} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '13px', color: 'white', fontWeight: '500' }}>{file.type.toUpperCase()}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{file.size_kb} KB</div>
                      </div>
                    </a>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '24px' }}>
          <Link href="/dashboard" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📊</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>仪表盘</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康数据</div>
            </div>
          </Link>
          <Link href="/report" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📋</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>AI 报告</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康分析</div>
            </div>
          </Link>
        </section>
      </main>
    </div>
  );
}

function FileIcon({ type }: { type: string }) {
  const icons: Record<string, string> = { pdf: '📕', html: '🌐', md: '📄', svg: '📊' };
  return <span style={{ fontSize: '20px' }}>{icons[type] || '📎'}</span>;
}
