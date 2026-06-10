'use client';

import { useState, useRef } from 'react';
import { Header } from '@/components/layout/header';
import { API_BASE, getAuthToken } from '@/lib/api';

interface UploadResult {
  filename: string;
  status: 'success' | 'error';
  message: string;
  summary?: string;
  facts_imported?: number;
}

const FILE_CATEGORIES = [
  { exts: ['.csv'], label: 'CSV 数据文件', icon: '📊', desc: '可穿戴设备导出的 CSV 数据（Apple Health / Garmin 等）' },
  { exts: ['.json'], label: 'JSON 健康数据', icon: '📋', desc: '健康数据 JSON 格式（Garmin Connect 导出等）' },
  { exts: ['.pdf'], label: 'PDF 医学报告', icon: '📕', desc: '血常规、体检报告等 PDF 文件' },
  { exts: ['.png', '.jpg', '.jpeg'], label: '图像文件', icon: '🖼️', desc: '体脂秤读数、化验单照片、医疗影像等' },
  { exts: ['.txt'], label: '文本文件', icon: '📄', desc: '纯文本健康记录' },
];

export default function UploadPage() {
  const [results, setResults] = useState<UploadResult[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;

    setUploading(true);
    const newResults: UploadResult[] = [];

    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);

      try {
        const res = await fetch(`${API_BASE}/upload/file`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${getAuthToken()}` },
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          newResults.push({ filename: file.name, status: 'error', message: err.detail || `上传失败 (${res.status})` });
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
      } catch (err) {
        newResults.push({ filename: file.name, status: 'error', message: err instanceof Error ? err.message : '网络错误' });
      }
    }

    setResults(prev => [...newResults, ...prev]);
    setUploading(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    uploadFiles(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const getFileCategory = (filename: string) => {
    const ext = '.' + filename.split('.').pop()?.toLowerCase();
    return FILE_CATEGORIES.find(c => c.exts.includes(ext));
  };

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="文件上传分析" activePath="/upload" />

      <main className="mx-auto max-w-[900px] p-6">
        {/* 拖拽上传区 */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          className="cursor-pointer rounded-lg border-2 border-dashed p-12 text-center transition-colors"
          style={{
            borderColor: dragOver ? 'var(--primary)' : 'var(--border)',
            background: dragOver ? 'rgba(0,201,167,0.05)' : 'var(--surface)',
          }}
        >
          <div className="mb-3 text-[40px]">{uploading ? '⏳' : '📁'}</div>
          <h3 className="mb-2 text-base font-medium text-white">
            {uploading ? '上传中...' : '点击或拖拽文件到此处'}
          </h3>
          <p className="text-[13px] text-[var(--text-muted)]">
            支持 CSV、JSON、PDF、PNG、JPG 格式，可批量上传
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={e => e.target.files && uploadFiles(e.target.files)}
            className="hidden"
            accept=".csv,.json,.pdf,.png,.jpg,.jpeg,.txt,.xml"
          />
        </div>

        {/* 支持的文件类型 */}
        <div className="mt-5 grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5">
          {FILE_CATEGORIES.map(cat => (
            <div key={cat.label} className="card p-3">
              <div className="mb-1 text-xl">{cat.icon}</div>
              <div className="text-[13px] font-medium text-white">{cat.label}</div>
              <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">{cat.desc}</div>
            </div>
          ))}
        </div>

        {/* 上传结果 */}
        {results.length > 0 && (
          <section className="mt-6">
            <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
              上传结果
            </h2>
            <div className="flex flex-col gap-2">
              {results.map((r, i) => {
                const cat = getFileCategory(r.filename);
                const isSuccess = r.status === 'success';
                return (
                  <div key={i} className="card flex items-start gap-3">
                    <span className="text-xl">{cat?.icon || '📎'}</span>
                    <div className="flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="text-[13px] font-medium text-white">{r.filename}</span>
                        <span
                          className="rounded text-[10px] font-medium text-white"
                          style={{
                            padding: '2px 8px',
                            background: isSuccess ? 'var(--success)' : 'var(--error)',
                          }}
                        >
                          {isSuccess ? '成功' : '失败'}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-secondary)]">{r.message}</p>
                      {r.facts_imported != null && (
                        <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                          入库 {r.facts_imported} 条事实数据
                        </p>
                      )}
                      {r.summary && (
                        <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{r.summary}</p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
