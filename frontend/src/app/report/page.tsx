'use client';

// /report — AI 健康报告(Stage 2:接入 8 组件库 + 错误处理)
// 2026-06-24 frontend-polish Stage 2

import { useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useReportStore } from '@/lib/stores/report-store';
import { Header } from '@/components/layout/header';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Skeleton,
  useToast,
} from '@/components/ui';

function formatTime(timestamp: string) {
  if (!timestamp) return '-';
  return timestamp.replace('T', ' ').substring(0, 19);
}

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
  const {
    reports,
    currentReport,
    loading,
    analyzing,
    downloading,
    error,
    fetchReports,
    fetchReport,
    triggerAnalyze,
    downloadReport,
  } = useReportStore();
  const toast = useToast();

  useEffect(() => {
    fetchReports().catch((e: unknown) =>
      toast.error(`报告列表加载失败: ${e instanceof Error ? e.message : e}`),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onAnalyze = async () => {
    try {
      await triggerAnalyze();
      toast.success('分析已触发,请稍候查看新报告');
    } catch (e) {
      toast.error(`触发失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const onDownload = async (id: number) => {
    try {
      await downloadReport(id);
      toast.success('下载完成');
    } catch (e) {
      toast.error(`下载失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header
        title={`报告 ${reports.length} 份`}
        activePath="/report"
        extra={
          <Button
            variant="primary"
            size="sm"
            onClick={onAnalyze}
            loading={analyzing}
          >
            ⟳ {analyzing ? '分析中...' : '重新分析'}
          </Button>
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
              {loading && reports.length === 0 ? (
                <>
                  <Skeleton height={70} />
                  <Skeleton height={70} />
                  <Skeleton height={70} />
                </>
              ) : reports.length === 0 ? (
                <Card>
                  <EmptyState
                    icon="📋"
                    title="暂无报告"
                    description="点击右上角「重新分析」生成第一份 AI 健康报告"
                  />
                </Card>
              ) : (
                reports.map((report) => {
                  const isSelected = currentReport?.id === report.id;
                  return (
                    <button
                      key={report.id}
                      onClick={() => fetchReport(report.id)}
                      aria-pressed={isSelected}
                      className={[
                        'cursor-pointer rounded-md p-3 text-left border transition-colors',
                        isSelected
                          ? 'bg-[var(--surface-elevated)] border-[var(--primary)]'
                          : 'bg-[var(--surface)] border-[var(--border)] hover:bg-[var(--surface-elevated)]',
                      ].join(' ')}
                    >
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-[11px] text-[var(--text-muted)]">{formatTime(report.timestamp)}</span>
                        {report.is_current ? (
                          <span className="rounded px-1.5 py-0.5 text-[10px] text-white bg-[var(--primary)]">
                            最新
                          </span>
                        ) : null}
                      </div>
                      <p className="truncate text-xs text-[var(--text-secondary)]">
                        {(report.content || (report as unknown as { preview?: string }).preview)?.substring(0, 60) ?? '无内容'}...
                      </p>
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Report Detail */}
          <div>
            {error && !loading ? (
              <ErrorState error={error} onRetry={() => fetchReports()} />
            ) : currentReport ? (
              <Card>
                <div className="mb-5 flex items-start justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-white">报告详情</h2>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      {formatTime(currentReport.timestamp)} · {currentReport.model}
                    </p>
                  </div>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => onDownload(currentReport.id)}
                    loading={downloading}
                  >
                    {downloading ? '下载中...' : '📥 下载'}
                  </Button>
                </div>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {currentReport.content || ''}
                </ReactMarkdown>
              </Card>
            ) : (
              <Card>
                <EmptyState icon="📋" title="选择左侧报告查看详情" />
              </Card>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}