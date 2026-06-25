'use client';

// /report — AI 健康报告 (2026-06-25: 新增数据源面板)
// Stage 2 接入 8 组件库 + 错误处理
// 2026-06-24 frontend-polish Stage 2
// 2026-06-25 frontend-evolution: 数据源面板 (一链点动入库+分析)

import { useEffect, useState } from 'react';
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

// 预置数据源 (2026-06-25)
const PRESET_SOURCES = [
  { id: 'garmin_20260526', label: '佳明数据 20260526', desc: '脱敏自张晨,30+ 条事实', icon: '📊' },
] as const;

export default function ReportPage() {
  const {
    reports,
    currentReport,
    loading,
    analyzing,
    ingesting,
    analyzeProgress,
    downloading,
    error,
    fetchReports,
    fetchReport,
    triggerAnalyze,
    triggerAnalyzeWithSource,
    downloadReport,
  } = useReportStore();
  const toast = useToast();

  // ── 数据源面板本地状态 ──
  const [urlInput, setUrlInput] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);

  useEffect(() => {
    fetchReports().catch((e: unknown) =>
      toast.error(`报告列表加载失败: ${e instanceof Error ? e.message : e}`),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 触发分析(三种入口) ──

  const onAnalyze = async () => {
    try {
      await triggerAnalyze();
      toast.success('分析已触发,请稍候查看新报告');
    } catch (e) {
      toast.error(`触发失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const onPresetSource = async (sourceId: string) => {
    try {
      await triggerAnalyzeWithSource({ source: sourceId as 'garmin_20260526' });
      toast.success('已选预置数据源 + AI 分析完成');
    } catch (e) {
      toast.error(`失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const onUploadAnalyze = async () => {
    if (stagedFiles.length === 0) {
      toast.error('请先选择文件');
      return;
    }
    try {
      await triggerAnalyzeWithSource({ source: 'upload', files: stagedFiles });
      toast.success(`已分析 ${stagedFiles.length} 个文件`);
      setStagedFiles([]);
    } catch (e) {
      toast.error(`失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  const onUrlAnalyze = async () => {
    if (!urlInput.trim()) {
      toast.error('请输入 URL');
      return;
    }
    try {
      await triggerAnalyzeWithSource({ source: 'url', url: urlInput.trim() });
      toast.success('URL 拉取 + AI 分析完成');
      setUrlInput('');
    } catch (e) {
      toast.error(`失败: ${e instanceof Error ? e.message : e}`);
    }
  };

  // ── 文件拖拽 ──
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      setStagedFiles(prev => [...prev, ...files]);
      toast.success(`已暂存 ${files.length} 个文件,点击「开始分析」入库`);
    }
  };
  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const files = Array.from(e.target.files);
      setStagedFiles(prev => [...prev, ...files]);
    }
    e.target.value = '';
  };
  const removeStagedFile = (idx: number) => {
    setStagedFiles(prev => prev.filter((_, i) => i !== idx));
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
        {/* 数据源面板 (2026-06-25) */}
        <Card className="mb-4">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-[var(--primary)]">📊</span>
            <h2 className="text-base font-semibold text-white">数据源</h2>
            <span className="text-[10px] text-[var(--text-muted)]">
              一链点动: 选数据源 → 自动入库 → 触发 LLM 重新分析
            </span>
          </div>

          {/* 预置目录 */}
          <div className="mb-3">
            <div className="mb-1.5 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              预置目录
            </div>
            <div className="flex flex-wrap gap-2">
              {PRESET_SOURCES.map(s => (
                <button
                  key={s.id}
                  onClick={() => onPresetSource(s.id)}
                  disabled={analyzing}
                  className="cursor-pointer rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-left transition-colors hover:border-[var(--primary)] hover:bg-[var(--surface-elevated)] disabled:opacity-50"
                >
                  <div className="text-sm text-white">
                    {s.icon} {s.label}
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)]">{s.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* 拖拽上传 */}
          <div className="mb-3">
            <div className="mb-1.5 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              拖拽上传 (CSV/JSON/TXT)
            </div>
            <div
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
              className={[
                'rounded-md border-2 border-dashed px-4 py-3 text-center text-xs transition-colors',
                dragOver
                  ? 'border-[var(--primary)] bg-[var(--surface-elevated)] text-white'
                  : 'border-[var(--border)] text-[var(--text-muted)]',
              ].join(' ')}
            >
              {stagedFiles.length > 0 ? (
                <div className="space-y-1">
                  {stagedFiles.map((f, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between rounded bg-[var(--surface-elevated)] px-2 py-1 text-[11px]"
                    >
                      <span className="truncate text-[var(--text-secondary)]">
                        📎 {f.name} ({Math.round(f.size / 1024)}KB)
                      </span>
                      <button
                        onClick={() => removeStagedFile(i)}
                        className="cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-white"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div>
                  ⬆ 拖拽文件到此处,或
                  <label className="ml-1 cursor-pointer text-[var(--primary)] underline">
                    选择文件
                    <input
                      type="file"
                      multiple
                      accept=".csv,.json,.txt"
                      onChange={onFileInput}
                      className="hidden"
                    />
                  </label>
                </div>
              )}
            </div>
            {stagedFiles.length > 0 && (
              <div className="mt-2 flex justify-end">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={onUploadAnalyze}
                  loading={ingesting}
                  disabled={analyzing && !ingesting}
                >
                  📤 分析 {stagedFiles.length} 个文件
                </Button>
              </div>
            )}
          </div>

          {/* URL 拉取 */}
          <div>
            <div className="mb-1.5 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              远程 URL
            </div>
            <div className="flex gap-2">
              <input
                type="url"
                value={urlInput}
                onChange={e => setUrlInput(e.target.value)}
                placeholder="https://example.com/data.json"
                disabled={analyzing}
                className="flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-[13px] text-white outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--primary)] disabled:opacity-50"
              />
              <Button
                size="md"
                variant="primary"
                onClick={onUrlAnalyze}
                loading={analyzing}
                disabled={!urlInput.trim()}
              >
                📥 拉取并分析
              </Button>
            </div>
          </div>

          {/* 进度条 */}
          {(analyzing || ingesting) && analyzeProgress && (
            <div className="mt-3 rounded-md border border-[var(--primary)]/30 bg-[var(--primary)]/10 px-3 py-2 text-[12px] text-[var(--primary)]">
              <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--primary)]" />
              {analyzeProgress}
            </div>
          )}
        </Card>

        {/* 报告列表 + 详情 */}
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
                    description="选择上方数据源,一链点动生成 AI 健康报告"
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
