'use client';

import { useEffect, useState } from 'react';
import { useLLMObserveStore } from '@/lib/stores/llm-observe-store';
import { Header } from '@/components/layout/header';
import ReactECharts from 'echarts-for-react';

const cardStyle: React.CSSProperties = {
  background: 'var(--surface)',
  borderRadius: 12,
  padding: 20,
  border: '1px solid var(--border)',
};

const kpiBox: React.CSSProperties = {
  background: 'var(--surface)',
  borderRadius: 10,
  padding: '16px 20px',
  border: '1px solid var(--border)',
  flex: '1 1 140px',
  minWidth: 140,
};

const severityColor: Record<string, string> = {
  critical: '#FF4757',
  warn: '#FFB800',
  info: '#00C9A7',
};

export default function LLMObservePage() {
  const {
    metrics, traces, suggestions, analysisReport,
    loading, error,
    fetchMetrics, fetchTraces, fetchSuggestions, runAnalysis,
  } = useLLMObserveStore();

  const [days, setDays] = useState(7);
  const [analysisLoading, setAnalysisLoading] = useState(false);

  useEffect(() => {
    fetchMetrics(days);
    fetchTraces(50, 0);
    fetchSuggestions(days);
  }, [days, fetchMetrics, fetchTraces, fetchSuggestions]);

  const handleAnalyze = async () => {
    setAnalysisLoading(true);
    await runAnalysis(days);
    setAnalysisLoading(false);
  };

  const trendOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { data: ['调用量', '平均延迟(ms)', 'Token 消耗'], textStyle: { color: '#aaa' } },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: {
      type: 'category' as const,
      data: metrics?.by_day.map(d => d.date) || [],
      axisLabel: { color: '#888' },
    },
    yAxis: [
      { type: 'value' as const, axisLabel: { color: '#888' } },
      { type: 'value' as const, axisLabel: { color: '#888' } },
    ],
    series: [
      {
        name: '调用量', type: 'bar', data: metrics?.by_day.map(d => d.calls) || [],
        itemStyle: { color: '#00C9A7' },
      },
      {
        name: '平均延迟(ms)', type: 'line', yAxisIndex: 1,
        data: metrics?.by_day.map(d => Math.round(d.avg_latency_ms)) || [],
        itemStyle: { color: '#FFB800' }, smooth: true,
      },
      {
        name: 'Token 消耗', type: 'line',
        data: metrics?.by_day.map(d => d.tokens) || [],
        itemStyle: { color: '#00D4FF' }, smooth: true,
      },
    ],
  };

  const modelPieOption = {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' as const },
    series: [{
      type: 'pie', radius: ['40%', '70%'],
      data: metrics?.by_model.map(m => ({
        name: m.model || 'unknown', value: m.calls,
      })) || [],
      label: { color: '#ccc' },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' },
      },
    }],
  };

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header title="LLM 观测" activePath="/llm-observe" />

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
        {/* 天数选择 */}
        <div style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ color: 'var(--text-secondary, #aaa)' }}>时间范围：</span>
          {[7, 14, 30].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              style={{
                padding: '6px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
                background: days === d ? '#00C9A7' : 'var(--surface)',
                color: days === d ? '#111' : '#ccc',
                fontWeight: days === d ? 600 : 400,
              }}
            >
              {d} 天
            </button>
          ))}
        </div>

        {error && (
          <div style={{
            ...cardStyle, marginBottom: 16,
            color: '#FF4757', fontSize: 14,
          }}>
            {error}
          </div>
        )}

        {/* KPI 行 */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
          {[
            { label: '总调用', value: metrics?.total_calls ?? '-', suffix: '' },
            { label: '成功率', value: metrics ? `${(metrics.success_rate * 100).toFixed(1)}%` : '-', suffix: '' },
            { label: '平均延迟', value: metrics?.avg_latency_ms ? `${Math.round(metrics.avg_latency_ms)}ms` : '-', suffix: '' },
            { label: 'P95 延迟', value: metrics?.p95_latency_ms ? `${Math.round(metrics.p95_latency_ms)}ms` : '-', suffix: '' },
            { label: 'Token 消耗', value: metrics?.total_tokens ?? '-', suffix: '' },
            { label: '总成本', value: metrics ? `$${metrics.total_cost.toFixed(4)}` : '-', suffix: '' },
          ].map(kpi => (
            <div key={kpi.label} style={kpiBox}>
              <div style={{ color: 'var(--text-secondary, #aaa)', fontSize: 12, marginBottom: 4 }}>
                {kpi.label}
              </div>
              <div style={{ color: '#00C9A7', fontSize: 22, fontWeight: 700 }}>
                {kpi.value}{kpi.suffix}
              </div>
            </div>
          ))}
        </div>

        {/* 趋势图 */}
        <div style={{ ...cardStyle, marginBottom: 20 }}>
          <h3 style={{ color: '#fff', margin: '0 0 12px' }}>调用趋势</h3>
          <ReactECharts option={trendOption} style={{ height: 300 }} />
        </div>

        {/* 模型分布 + 成本 */}
        <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
          <div style={{ ...cardStyle, flex: 1 }}>
            <h3 style={{ color: '#fff', margin: '0 0 12px' }}>模型调用分布</h3>
            <ReactECharts option={modelPieOption} style={{ height: 250 }} />
          </div>
          <div style={{ ...cardStyle, flex: 1 }}>
            <h3 style={{ color: '#fff', margin: '0 0 12px' }}>模型明细</h3>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ color: '#888', borderBottom: '1px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: 4 }}>模型</th>
                  <th style={{ textAlign: 'right', padding: 4 }}>调用</th>
                  <th style={{ textAlign: 'right', padding: 4 }}>延迟</th>
                  <th style={{ textAlign: 'right', padding: 4 }}>成本</th>
                </tr>
              </thead>
              <tbody>
                {metrics?.by_model.map(m => (
                  <tr key={m.model} style={{ borderBottom: '1px solid #222' }}>
                    <td style={{ color: '#ccc', padding: 6 }}>{m.model || 'unknown'}</td>
                    <td style={{ color: '#ccc', textAlign: 'right', padding: 6 }}>{m.calls}</td>
                    <td style={{ color: '#FFB800', textAlign: 'right', padding: 6 }}>
                      {Math.round(m.avg_latency_ms)}ms
                    </td>
                    <td style={{ color: '#00C9A7', textAlign: 'right', padding: 6 }}>
                      ${m.cost?.toFixed(4) ?? '0'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 优化建议 */}
        <div style={{ ...cardStyle, marginBottom: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h3 style={{ color: '#fff', margin: 0 }}>优化建议</h3>
            <button
              onClick={handleAnalyze}
              disabled={analysisLoading}
              style={{
                padding: '8px 20px', borderRadius: 8,
                background: analysisLoading ? '#333' : '#00C9A7',
                color: analysisLoading ? '#666' : '#111',
                border: 'none', cursor: analysisLoading ? 'not-allowed' : 'pointer',
                fontWeight: 600, fontSize: 13,
              }}
            >
              {analysisLoading ? 'AI 分析中...' : 'AI 深度分析'}
            </button>
          </div>

          {suggestions.length === 0 && !analysisReport && (
            <div style={{ color: '#666', fontSize: 14 }}>暂无优化建议（需要 LLM 调用数据）</div>
          )}

          {suggestions.map((s, i) => (
            <div
              key={i}
              style={{
                padding: 12, marginBottom: 8, borderRadius: 8,
                background: '#1a1a1a',
                borderLeft: `3px solid ${severityColor[s.severity] || '#666'}`,
              }}
            >
              <div style={{ color: severityColor[s.severity], fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
                [{s.severity.toUpperCase()}] {s.title}
              </div>
              <div style={{ color: '#aaa', fontSize: 13 }}>{s.detail}</div>
            </div>
          ))}

          {analysisReport && (
            <div style={{
              marginTop: 16, padding: 16, borderRadius: 8,
              background: '#1a1a1a', border: '1px solid #333',
            }}>
              <h4 style={{ color: '#00C9A7', margin: '0 0 8px' }}>AI 优化报告</h4>
              <div style={{ color: '#ccc', fontSize: 13, whiteSpace: 'pre-wrap' }}>
                {analysisReport}
              </div>
            </div>
          )}
        </div>

        {/* Trace 列表 */}
        <div style={cardStyle}>
          <h3 style={{ color: '#fff', margin: '0 0 12px' }}>最近调用记录</h3>
          {loading && <div style={{ color: '#666' }}>加载中...</div>}
          {!loading && traces.length === 0 && (
            <div style={{ color: '#666', fontSize: 14 }}>暂无 Trace 数据</div>
          )}
          {traces.map(t => (
            <div
              key={t.id}
              style={{
                display: 'flex', gap: 12, alignItems: 'center',
                padding: '10px 0', borderBottom: '1px solid #222',
                fontSize: 13,
              }}
            >
              <span style={{ color: '#888', fontFamily: 'monospace', fontSize: 11, width: 80 }}>
                {t.id.slice(0, 8)}
              </span>
              <span style={{ color: '#ccc', flex: 1 }}>{t.name}</span>
              <span style={{ color: '#888', width: 100 }}>{t.model || '-'}</span>
              <span style={{
                color: t.status === 'success' ? '#00C9A7' : '#FF4757',
                width: 60,
              }}>
                {t.status}
              </span>
              <span style={{ color: '#FFB800', width: 70 }}>
                {t.latency_ms ? `${Math.round(t.latency_ms)}ms` : '-'}
              </span>
              <span style={{ color: '#00D4FF', width: 60 }}>{t.tokens} tok</span>
              <span style={{ color: '#00C9A7', width: 70 }}>
                ${(t.cost || 0).toFixed(4)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
