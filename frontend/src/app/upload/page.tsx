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
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header title="文件上传分析" activePath="/upload" />

      <main style={{ padding: '24px', maxWidth: '900px', margin: '0 auto' }}>
        {/* 拖拽上传区 */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={() => setDragOver(false)}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${dragOver ? 'var(--primary)' : 'var(--border)'}`,
            borderRadius: '12px', padding: '48px 24px', textAlign: 'center',
            cursor: 'pointer', transition: 'border-color 0.2s',
            background: dragOver ? 'rgba(0,201,167,0.05)' : 'var(--surface)',
          }}
        >
          <div style={{ fontSize: '40px', marginBottom: '12px' }}>{uploading ? '⏳' : '📁'}</div>
          <h3 style={{ fontSize: '16px', color: 'white', fontWeight: '500', marginBottom: '8px' }}>
            {uploading ? '上传中...' : '点击或拖拽文件到此处'}
          </h3>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
            支持 CSV、JSON、PDF、PNG、JPG 格式，可批量上传
          </p>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={e => e.target.files && uploadFiles(e.target.files)}
            style={{ display: 'none' }}
            accept=".csv,.json,.pdf,.png,.jpg,.jpeg,.txt,.xml"
          />
        </div>

        {/* 支持的文件类型 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', marginTop: '20px' }}>
          {FILE_CATEGORIES.map(cat => (
            <div key={cat.label} className="card" style={{ padding: '12px' }}>
              <div style={{ fontSize: '20px', marginBottom: '4px' }}>{cat.icon}</div>
              <div style={{ fontSize: '13px', color: 'white', fontWeight: '500' }}>{cat.label}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{cat.desc}</div>
            </div>
          ))}
        </div>

        {/* 上传结果 */}
        {results.length > 0 && (
          <section style={{ marginTop: '24px' }}>
            <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              上传结果
            </h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {results.map((r, i) => {
                const cat = getFileCategory(r.filename);
                return (
                  <div key={i} className="card" style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
                    <span style={{ fontSize: '20px' }}>{cat?.icon || '📎'}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <span style={{ fontSize: '13px', color: 'white', fontWeight: '500' }}>{r.filename}</span>
                        <span style={{
                          fontSize: '10px', padding: '2px 8px', borderRadius: '4px',
                          background: r.status === 'success' ? 'var(--success)' : 'var(--error)',
                          color: 'white', fontWeight: '500',
                        }}>
                          {r.status === 'success' ? '成功' : '失败'}
                        </span>
                      </div>
                      <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{r.message}</p>
                      {r.facts_imported != null && (
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>入库 {r.facts_imported} 条事实数据</p>
                      )}
                      {r.summary && (
                        <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{r.summary}</p>
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
