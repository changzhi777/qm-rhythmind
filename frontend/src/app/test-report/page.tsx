'use client';

// /test-report — E2E 测试报告(Stage 4:接入 8 组件 + 错误处理)
// 2026-06-24 frontend-polish Stage 4

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Header } from '@/components/layout/header';
import { Card, EmptyState, ErrorState, Skeleton, useToast } from '@/components/ui';
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
  const toast = useToast();

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
      toast.success(`已下载 ${filename}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '下载失败';
      setError(msg);
      toast.error(`下载失败: ${msg}`);
    } finally {
      setDownloading(null);
    }
  };

  useEffect(() => {
    async function fetchReports() {
      setError(null);
      try {
        const token = getAuthToken();
        const res = await fetch(`${API_BASE}/test-reports`, {
          headers: { 'Authorization': `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setReports(data.reports || []);
      } catch (e) {
        const msg = e instanceof Error ? e.message : '获取报告失败';
        setError(msg);
        toast.error(`报告列表加载失败: ${msg}`);
      } finally {
        setLoading(false);
      }
    }
    fetchReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="测试报告" activePath="/test-report" maxWidth="1200px" />

      <main className="mx-auto max-w-[1200px] p-6">
        <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
          E2E 测试报告列表
        </h2>

        {loading ? (
          <div className="space-y-3">
            <Skeleton height={120} />
            <Skeleton height={120} />
          </div>
        ) : error ? (
          <Card>
            <ErrorState
              error={error}
              title="加载失败"
              action={
                <p className="mt-2 text-xs text-[var(--text-muted)]">
                  提示:运行 <code className="rounded bg-[var(--surface-elevated)] px-1.5 py-0.5">python3 tests/e2e_test.py --upload</code> 生成并上传报告
                </p>
              }
            />
          </Card>
        ) : reports.length === 0 ? (
          <Card>
            <EmptyState
              icon="📋"
              title="暂无测试报告"
              description={
                <>
                  运行 <code className="rounded bg-[var(--surface-elevated)] px-1.5 py-0.5">python3 tests/e2e_test.py --upload</code> 生成并上传报告到服务器
                </>
              }
            />
          </Card>
        ) : (
          <div className="flex flex-col gap-4">
            {reports.map((report) => {
              const isAllPass = report.pass_rate === 100;
              return (
                <Card key={report.id}>
                  <div className="mb-4 flex items-start justify-between">
                    <div>
                      <div className="mb-1 flex items-center gap-2">
                        <h3 className="text-[15px] font-semibold text-white">
                          {report.timestamp.replace('T', ' ').substring(0, 19)}
                        </h3>
                        <span
                          className={[
                            'rounded px-2 py-0.5 text-[10px] font-medium text-white',
                            isAllPass ? 'bg-[var(--status-good)]' : 'bg-[var(--status-concerned)]',
                          ].join(' ')}
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
                        disabled={downloading === file.name}
                        aria-busy={downloading === file.name || undefined}
                        className="flex w-full cursor-pointer items-center gap-2 rounded-md border-none px-3 py-2.5 bg-[var(--surface-elevated)] hover:bg-[var(--surface)] transition-colors disabled:opacity-50"
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
                </Card>
              );
            })}
          </div>
        )}

        <section className="mt-6 grid grid-cols-2 gap-3">
          <Link href="/dashboard" className="contents">
            <Card interactive>
              <div className="flex items-center gap-3">
                <span className="text-xl" aria-hidden="true">📊</span>
                <div>
                  <div className="text-sm font-medium text-white">仪表盘</div>
                  <div className="text-xs text-[var(--text-muted)]">健康数据</div>
                </div>
              </div>
            </Card>
          </Link>
          <Link href="/report" className="contents">
            <Card interactive>
              <div className="flex items-center gap-3">
                <span className="text-xl" aria-hidden="true">📋</span>
                <div>
                  <div className="text-sm font-medium text-white">AI 报告</div>
                  <div className="text-xs text-[var(--text-muted)]">健康分析</div>
                </div>
              </div>
            </Card>
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
