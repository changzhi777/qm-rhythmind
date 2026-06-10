'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Header } from '@/components/layout/header';
import { API_BASE, getAuthToken } from '@/lib/api';

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
  const [downloading, setDownloading] = useState<string | null>(null);

  const downloadFile = async (url: string, filename: string) => {
    if (downloading) return;
    setDownloading(filename);
    try {
      const res = await fetch(url, { headers: { 'Authorization': `Bearer ${getAuthToken()}` } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(a.href);
    } catch (e) {
      setError(e instanceof Error ? e.message : '下载失败');
    } finally {
      setDownloading(null);
    }
  };

  useEffect(() => {
    async function fetchReports() {
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/test-reports`, {
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
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="测试报告" activePath="/test-report" maxWidth="1200px" />

      <main className="mx-auto max-w-[1200px] p-6">
        <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
          E2E 测试报告列表
        </h2>

        {loading ? (
          <div className="py-12 text-center text-[var(--text-muted)]">加载中...</div>
        ) : error ? (
          <div className="card py-12 text-center">
            <div className="mb-2 text-[32px]">⚠️</div>
            <p className="text-[13px] text-[var(--error)]">{error}</p>
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              提示：通过 <code className="rounded bg-[var(--surface-elevated)] px-1.5 py-0.5">python3 tests/e2e_test.py --upload</code> 生成并上传报告
            </p>
          </div>
        ) : reports.length === 0 ? (
          <div className="card py-12 text-center">
            <div className="mb-2 text-[32px]">📋</div>
            <p className="text-[13px] text-[var(--text-muted)]">暂无测试报告</p>
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              运行 <code className="rounded bg-[var(--surface-elevated)] px-1.5 py-0.5">python3 tests/e2e_test.py --upload</code> 生成并上传报告到服务器
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {reports.map((report) => {
              const isAllPass = report.pass_rate === 100;
              return (
                <div key={report.id} className="card">
                  <div className="mb-4 flex items-start justify-between">
                    <div>
                      <div className="mb-1 flex items-center gap-2">
                        <h3 className="text-[15px] font-semibold text-white">
                          {report.timestamp.replace('T', ' ').substring(0, 19)}
                        </h3>
                        <span
                          className="rounded text-[10px] font-medium text-white"
                          style={{
                            padding: '2px 8px',
                            background: isAllPass ? 'var(--success)' : 'var(--warning)',
                          }}
                        >
                          {report.pass_rate.toFixed(1)}%
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)]">
                        {report.rounds} 轮 · {report.passed}/{report.total} 通过 · 页面 {report.page_avg_ms}ms · API {report.api_avg_ms}ms
                      </p>
                    </div>
                  </div>

                  <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2">
                    {report.files.map((file) => (
                      <button
                        key={file.name}
                        onClick={() => downloadFile(file.url, file.name)}
                        className="card flex w-full cursor-pointer items-center gap-2 border-none"
                        style={{
                          padding: '10px 12px',
                          background: 'var(--surface-elevated)',
                        }}
                      >
                        <FileIcon type={file.type} />
                        <div className="flex-1 text-left">
                          <div className="text-[13px] font-medium text-white">
                            {downloading === file.name ? '下载中...' : file.type.toUpperCase()}
                          </div>
                          <div className="text-[11px] text-[var(--text-muted)]">{file.size_kb} KB</div>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <section className="mt-6 grid grid-cols-2 gap-3">
          <Link href="/dashboard" className="card">
            <span className="text-xl">📊</span>
            <div>
              <div className="text-sm font-medium text-white">仪表盘</div>
              <div className="text-xs text-[var(--text-muted)]">健康数据</div>
            </div>
          </Link>
          <Link href="/report" className="card">
            <span className="text-xl">📋</span>
            <div>
              <div className="text-sm font-medium text-white">AI 报告</div>
              <div className="text-xs text-[var(--text-muted)]">健康分析</div>
            </div>
          </Link>
        </section>
      </main>
    </div>
  );
}

function FileIcon({ type }: { type: string }) {
  const icons: Record<string, string> = { pdf: '📕', html: '🌐', md: '📄', svg: '📊' };
  return <span className="text-xl">{icons[type] || '📎'}</span>;
}
