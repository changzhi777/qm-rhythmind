'use client';

import { useEffect } from 'react';
import { useReportStore } from '@/lib/stores/report-store';
import { Header } from '@/components/layout/header';

function formatTime(timestamp: string) {
  if (!timestamp) return '-';
  return timestamp.replace('T', ' ').substring(0, 19);
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMarkdown(text: string): string {
  if (!text) return '';

  const lines = text.split('\n');
  const htmlParts: string[] = [];
  let inList = false;

  for (const rawLine of lines) {
    const line = escapeHtml(rawLine);
    if (line.startsWith('### ')) {
      if (inList) { htmlParts.push('</ul>'); inList = false; }
      htmlParts.push(`<h3 style="font-size:14px;font-weight:500;color:white;margin:16px 0 8px">${line.slice(4)}</h3>`);
    } else if (line.startsWith('## ')) {
      if (inList) { htmlParts.push('</ul>'); inList = false; }
      htmlParts.push(`<h2 style="font-size:16px;font-weight:600;color:white;margin:20px 0 12px">${line.slice(3)}</h2>`);
    } else if (line.startsWith('# ')) {
      if (inList) { htmlParts.push('</ul>'); inList = false; }
      htmlParts.push(`<h1 style="font-size:20px;font-weight:700;color:white;margin:0 0 16px">${line.slice(2)}</h1>`);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      if (!inList) { htmlParts.push('<ul style="list-style:disc;padding-left:20px;margin:8px 0">'); inList = true; }
      const content = line.slice(2).replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight:600;color:var(--primary)">$1</strong>');
      htmlParts.push(`<li style="margin:4px 0;color:var(--text-secondary);font-size:13px">${content}</li>`);
    } else if (line.trim() === '') {
      if (inList) { htmlParts.push('</ul>'); inList = false; }
    } else {
      if (inList) { htmlParts.push('</ul>'); inList = false; }
      const content = line.replace(/\*\*(.+?)\*\*/g, '<strong style="font-weight:600;color:var(--primary)">$1</strong>');
      htmlParts.push(`<p style="margin:8px 0;color:var(--text-secondary);font-size:13px;line-height:1.6">${content}</p>`);
    }
  }

  if (inList) htmlParts.push('</ul>');
  return htmlParts.join('');
}

export default function ReportPage() {
  const { reports, currentReport, loading, analyzing, downloading, fetchReports, fetchReport, triggerAnalyze, downloadReport } = useReportStore();

  useEffect(() => { fetchReports(); }, [fetchReports]);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header
        title={`报告 ${reports.length} 份`}
        activePath="/report"
        extra={
          <button onClick={triggerAnalyze} disabled={analyzing} className="btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {analyzing ? <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⟳</span> : '⚡'}
            {analyzing ? '分析中...' : '重新分析'}
          </button>
        }
      />

      <main style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '16px' }}>
          {/* Report List */}
          <div>
            <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>报告列表</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {reports.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)', fontSize: '13px' }}>
                  {loading ? '加载中...' : '暂无报告'}
                </div>
              ) : (
                reports.map((report) => (
                  <button
                    key={report.id}
                    onClick={() => fetchReport(report.id)}
                    style={{
                      padding: '12px',
                      background: currentReport?.id === report.id ? 'var(--surface-elevated)' : 'var(--surface)',
                      border: `1px solid ${currentReport?.id === report.id ? 'var(--primary)' : 'var(--border)'}`,
                      borderRadius: '6px',
                      textAlign: 'left',
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{formatTime(report.timestamp)}</span>
                      {report.is_current && <span style={{ fontSize: '10px', padding: '2px 6px', background: 'var(--primary)', color: 'white', borderRadius: '4px' }}>最新</span>}
                    </div>
                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {report.content?.substring(0, 60) ?? '无内容'}...
                    </p>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Report Detail */}
          <div>
            {currentReport ? (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px' }}>
                  <div>
                    <h2 style={{ fontSize: '16px', fontWeight: '600', color: 'white' }}>报告详情</h2>
                    <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
                      {formatTime(currentReport.timestamp)} · {currentReport.model}
                    </p>
                  </div>
                  <button
                    onClick={() => downloadReport(currentReport.id)}
                    disabled={downloading}
                    className="btn-primary"
                    style={{ display: 'flex', alignItems: 'center', gap: '6px', opacity: downloading ? 0.6 : 1 }}
                  >
                    {downloading ? '⏳ 下载中...' : '📥 下载'}
                  </button>
                </div>
                <div dangerouslySetInnerHTML={{ __html: renderMarkdown(currentReport.content) }} />
              </div>
            ) : (
              <div className="card" style={{ minHeight: '320px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '32px', marginBottom: '8px' }}>📋</div>
                  <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>选择左侧报告查看详情</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
