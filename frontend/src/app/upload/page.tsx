'use client';

// /upload — 数据上传(Stage 2:接入 8 组件 + a11y 修复 + 错误处理)
// 2026-06-24 frontend-polish Stage 2

import { useState, useRef, type DragEvent, type KeyboardEvent } from 'react';
import { Header } from '@/components/layout/header';
import { Card, EmptyState, useToast } from '@/components/ui';
import { API_BASE, getAuthToken } from '@/lib/api';

interface UploadResult {
  filename: string;
  status: 'success' | 'error';
  message: string;
  summary?: string;
  facts_imported?: number;
}

const FILE_CATEGORIES = [
  { exts: ['.csv'], label: 'CSV 数据文件', icon: '📊', desc: '可穿戴设备导出的 CSV 数据(Apple Health / Garmin 等)' },
  { exts: ['.json'], label: 'JSON 健康数据', icon: '📋', desc: '健康数据 JSON 格式(Garmin Connect 导出等)' },
  { exts: ['.pdf'], label: 'PDF 医学报告', icon: '📕', desc: '血常规、体检报告等 PDF 文件' },
  { exts: ['.png', '.jpg', '.jpeg'], label: '图像文件', icon: '🖼️', desc: '体脂秤读数、化验单照片、医疗影像等' },
  { exts: ['.txt'], label: '文本文件', icon: '📄', desc: '纯文本健康记录' },
];

export default function UploadPage() {
  const [results, setResults] = useState<UploadResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const uploadFiles = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    setUploading(true);
    const newResults: UploadResult[] = [];
    let successCount = 0;
    let errorCount = 0;

    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch(`${API_BASE}/upload/file`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${getAuthToken()}` },
          body: formData,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          newResults.push({
            filename: file.name,
            status: 'error',
            message: err.detail || `上传失败 (${res.status})`,
          });
          errorCount++;
          continue;
        }
        const data = await res.json();
        newResults.push({
          filename: file.name,
          status: 'success',
          message: data.message || '上传成功',
          summary: data.summary,
          facts_imported: data.facts_imported,
        });
        successCount++;
      } catch (err) {
        newResults.push({
          filename: file.name,
          status: 'error',
          message: err instanceof Error ? err.message : '网络错误',
        });
        errorCount++;
      }
    }

    setResults((prev) => [...newResults, ...prev]);
    setUploading(false);

    // 阶段总结
    if (successCount > 0 && errorCount === 0) {
      toast.success(`成功上传 ${successCount} 个文件`);
    } else if (successCount > 0 && errorCount > 0) {
      toast.warning(`${successCount} 个成功,${errorCount} 个失败`);
    } else if (errorCount > 0) {
      toast.error(`全部 ${errorCount} 个文件上传失败`);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    void uploadFiles(e.dataTransfer.files);
  };
  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(true);
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      fileInputRef.current?.click();
    }
  };

  const getFileCategory = (filename: string) => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    return FILE_CATEGORIES.find((c) => c.exts.includes(ext));
  };

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="文件上传分析" activePath="/upload" />

      <main className="mx-auto max-w-[900px] p-6">
        {/* 拖拽上传区(a11y 修复:role/aria-label/tabIndex) */}
        <div
          role="button"
          tabIndex={0}
          aria-label="点击或按回车选择文件,也支持拖拽"
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={onKey}
          className={[
            'cursor-pointer rounded-lg border-2 border-dashed p-12 text-center transition-colors outline-none',
            'focus-visible:border-[var(--primary)] focus-visible:ring-2 focus-visible:ring-[var(--primary)] focus-visible:ring-offset-2',
            dragOver
              ? 'border-[var(--primary)] bg-[rgba(0,201,167,0.05)]'
              : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--text-muted)]',
          ].join(' ')}
        >
          <div className="mb-3 text-[40px]" aria-hidden="true">
            {uploading ? '⏳' : '📁'}
          </div>
          <h3 className="mb-2 text-base font-medium text-white">
            {uploading ? '上传中...' : '点击、按键或拖拽文件到此处'}
          </h3>
          <p className="text-[13px] text-[var(--text-muted)]">
            支持 CSV、JSON、PDF、PNG、JPG 格式,可批量上传
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={(e) => e.target.files && void uploadFiles(e.target.files)}
            className="hidden"
            accept=".csv,.json,.pdf,.png,.jpg,.jpeg,.txt,.xml"
            aria-hidden="true"
          />
        </div>

        {/* 支持的文件类型 */}
        <div className="mt-5 grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5">
          {FILE_CATEGORIES.map((cat) => (
            <Card key={cat.label}>
              <div className="mb-1 text-xl" aria-hidden="true">{cat.icon}</div>
              <div className="text-[13px] font-medium text-white">{cat.label}</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{cat.desc}</div>
            </Card>
          ))}
        </div>

        {/* 上传结果 */}
        {results.length > 0 ? (
          <section className="mt-6">
            <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
              上传结果
            </h2>
            <div className="flex flex-col gap-2">
              {results.map((r, i) => {
                const cat = getFileCategory(r.filename);
                const isSuccess = r.status === 'success';
                return (
                  <Card key={`${r.filename}-${i}`}>
                    <div className="flex items-start gap-3">
                      <span className="text-xl" aria-hidden="true">{cat?.icon || '📎'}</span>
                      <div className="flex-1">
                        <div className="mb-1 flex items-center gap-2">
                          <span className="text-[13px] font-medium text-white">{r.filename}</span>
                          <span
                            className={[
                              'rounded px-2 py-0.5 text-[10px] font-medium text-white',
                              isSuccess ? 'bg-[var(--status-good)]' : 'bg-[var(--status-danger)]',
                            ].join(' ')}
                          >
                            {isSuccess ? '成功' : '失败'}
                          </span>
                        </div>
                        <p className="text-xs text-[var(--text-secondary)]">{r.message}</p>
                        {r.facts_imported != null ? (
                          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                            入库 {r.facts_imported} 条事实数据
                          </p>
                        ) : null}
                        {r.summary ? (
                          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{r.summary}</p>
                        ) : null}
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          </section>
        ) : (
          <section className="mt-6">
            <Card>
              <EmptyState
                icon="📤"
                title="还没有上传记录"
                description="支持上传后自动分析并入库"
              />
            </Card>
          </section>
        )}
      </main>
    </div>
  );
}