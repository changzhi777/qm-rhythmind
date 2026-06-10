'use client';

import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useReportStore } from '@/lib/stores/report-store';
import { Header } from '@/components/layout/header';

function formatTime(timestamp: string) {
  if (!timestamp) return '-';
  return timestamp.replace('T', ' ').substring(0, 19);
}

// react-markdown 自定义组件 — 保持原自写 renderMarkdown 的视觉风格
const markdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-4 mt-0 text-xl font-bold text-white">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-3 mt-5 text-base font-semibold text-white">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-2 mt-4 text-sm font-medium text-white">{children}</h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="my-2 text-[13px] leading-relaxed text-[var(--text-secondary)]">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-2 list-disc pl-5">{children}</ul>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="my-1 text-[13px] text-[var(--text-secondary)]">{children}</li>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-[var(--primary)]">{children}</strong>
  ),
};

export default function ReportPage() {
  const { reports, currentReport, loading, analyzing, downloading, fetchReports, fetchReport, triggerAnalyze, downloadReport } = useReportStore();

  useEffect(() => { fetchReports(); }, [fetchReports]);

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header
        title={`报告 ${reports.length} 份`}
        activePath="/report"
        extra={
          <button
            onClick={triggerAnalyze}
            disabled={analyzing}
            className="btn-primary flex items-center gap-1.5"
          >
            <span
              className="inline-block"
              style={{
                animation: analyzing ? 'spin 1s linear infinite' : 'none',
              }}
            >
              ⟳
            </span>
            {analyzing ? '分析中...' : '重新分析'}
          </button>
        }
      />

      <main className="mx-auto max-w-[1200px] p-6">
        <div className="grid grid-cols-[280px_1fr] gap-4">
          {/* Report List */}
          <div>
            <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
              报告列表
            </h2>
            <div className="flex flex-col gap-2">
              {reports.length === 0 ? (
                <div className="py-8 text-center text-[13px] text-[var(--text-muted)]">
                  {loading ? '加载中...' : '暂无报告'}
                </div>
              ) : (
                reports.map((report) => {
                  const isSelected = currentReport?.id === report.id;
                  return (
                    <button
                      key={report.id}
                      onClick={() => fetchReport(report.id)}
                      className="cursor-pointer rounded-md p-3 text-left"
                      style={{
                        background: isSelected ? 'var(--surface-elevated)' : 'var(--surface)',
                        border: `1px solid ${isSelected ? 'var(--primary)' : 'var(--border)'}`,
                      }}
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[11px] text-[var(--text-muted)]">{formatTime(report.timestamp)}</span>
                        {report.is_current && (
                          <span
                            className="rounded text-[10px] text-white"
                            style={{
                              padding: '2px 6px',
                              background: 'var(--primary)',
                            }}
                          >
                            最新
                          </span>
                        )}
                      </div>
                      <p className="truncate text-xs text-[var(--text-secondary)]">
                        {report.content?.substring(0, 60) ?? '无内容'}...
                      </p>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Report Detail */}
          <div>
            {currentReport ? (
              <div className="card">
                <div className="mb-5 flex items-start justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-white">报告详情</h2>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      {formatTime(currentReport.timestamp)} · {currentReport.model}
                    </p>
                  </div>
                  <button
                    onClick={() => downloadReport(currentReport.id)}
                    disabled={downloading}
                    className="btn-primary flex items-center gap-1.5"
                    style={{ opacity: downloading ? 0.6 : 1 }}
                  >
                    {downloading ? '⏳ 下载中...' : '📥 下载'}
                  </button>
                </div>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {currentReport.content || ''}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="card flex min-h-[320px] items-center justify-center">
                <div className="text-center">
                  <div className="mb-2 text-[32px]">📋</div>
                  <p className="text-[13px] text-[var(--text-muted)]">选择左侧报告查看详情</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
