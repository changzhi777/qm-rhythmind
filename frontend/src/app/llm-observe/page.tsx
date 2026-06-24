'use client';

// /llm-observe — LLM 观测(Stage 3:接入 8 组件 + 错误处理)
// 2026-06-24 frontend-polish Stage 3

import { useEffect, useState } from 'react';
import { useLLMObserveStore } from '@/lib/stores/llm-observe-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { Button, Skeleton, useToast } from '@/components/ui';
import ReactECharts from 'echarts-for-react';

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
  const toast = useToast();

  useEffect(() => {
    fetchMetrics(days).catch((e: unknown) =>
      toast.error(`指标加载失败: ${e instanceof Error ? e.message : e}`),
    );
    fetchTraces(50, 0).catch(() => undefined);
    fetchSuggestions(days).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  const handleAnalyze = async () => {
    setAnalysisLoading(true);
    try {
      await runAnalysis(days);
      toast.success('AI 分析完成');
    } catch (e) {
      toast.error(`分析失败: ${e instanceof Error ? e.message : e}`);
    } finally {
      setAnalysisLoading(false);
    }
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
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="LLM 观测" activePath="/llm-observe" />

      <div className="mx-auto max-w-[1200px] p-6">
        {/* 天数选择 */}
        <div className="mb-4 flex items-center gap-2">
          <span className="text-[var(--text-secondary,#aaa)]">时间范围：</span>
          {[7, 14, 30].map(d => {
            const active = days === d;
            return (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`cursor-pointer rounded-md border-none px-4 py-1.5 ${active ? 'bg-[#00C9A7] text-[#111] font-semibold' : 'bg-[var(--surface)] text-[#ccc] font-normal'}`}
              >
                {d} 天
              </button>
            );
          })}
        </div>

        {error && (
          <div className="card mb-5 text-sm text-[var(--error)]">
            {error}
          </div>
        )}

        {/* KPI 行 */}
        <div className="mb-5 flex flex-wrap gap-3">
          {loading ? (
            <>
              <Skeleton height={60} width={140} />
              <Skeleton height={60} width={140} />
              <Skeleton height={60} width={140} />
              <Skeleton height={60} width={140} />
              <Skeleton height={60} width={140} />
              <Skeleton height={60} width={140} />
            </>
          ) : (
            [
              { label: '总调用', value: metrics?.total_calls ?? '-', unit: '' },
              { label: '成功率', value: metrics ? `${(metrics.success_rate * 100).toFixed(1)}%` : '-', unit: '' },
              { label: '平均延迟', value: metrics?.avg_latency_ms ? Math.round(metrics.avg_latency_ms) : '-', unit: metrics?.avg_latency_ms ? 'ms' : '' },
              { label: 'P95 延迟', value: metrics?.p95_latency_ms ? Math.round(metrics.p95_latency_ms) : '-', unit: metrics?.p95_latency_ms ? 'ms' : '' },
              { label: 'Token 消耗', value: metrics?.total_tokens ?? '-', unit: '' },
              { label: '总成本', value: metrics ? `$${metrics.total_cost.toFixed(4)}` : '-', unit: '' },
            ].map(kpi => (
              <KpiCard
                key={kpi.label}
                title={kpi.label}
                value={kpi.value}
                unit={kpi.unit}
                status="excellent"
              />
            ))
          )}
        </div>

        {/* 趋势图 */}
        <div className="card mb-5">
          <h3 className="mb-3 mt-0 text-white">调用趋势</h3>
          <ReactECharts option={trendOption} style={{ height: 300 }} />
        </div>

        {/* 模型分布 + 成本 */}
        <div className="mb-5 flex gap-4">
          <div className="card flex-1">
            <h3 className="mb-3 mt-0 text-white">模型调用分布</h3>
            <ReactECharts option={modelPieOption} style={{ height: 250 }} />
          </div>
          <div className="card flex-1">
            <h3 className="mb-3 mt-0 text-white">模型明细</h3>
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="border-b border-[var(--border)] text-[#888]">
                  <th className="p-1 text-left">模型</th>
                  <th className="p-1 text-right">调用</th>
                  <th className="p-1 text-right">延迟</th>
                  <th className="p-1 text-right">成本</th>
                </tr>
              </thead>
              <tbody>
                {metrics?.by_model.map(m => (
                  <tr key={m.model} className="border-b border-[#222]">
                    <td className="p-1.5 text-[#ccc]">{m.model || 'unknown'}</td>
                    <td className="p-1.5 text-right text-[#ccc]">{m.calls}</td>
                    <td className="p-1.5 text-right text-[#FFB800]">
                      {Math.round(m.avg_latency_ms)}ms
                    </td>
                    <td className="p-1.5 text-right text-[#00C9A7]">
                      ${m.cost?.toFixed(4) ?? '0'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 优化建议 */}
        <div className="card mb-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="m-0 text-white">优化建议</h3>
            <Button variant="primary" size="md" onClick={handleAnalyze} loading={analysisLoading}>
              {analysisLoading ? 'AI 分析中...' : 'AI 深度分析'}
            </Button>
          </div>

          {suggestions.length === 0 && !analysisReport && (
            <div className="text-sm text-[#666]">暂无优化建议（需要 LLM 调用数据）</div>
          )}

          {suggestions.map((s, i) => (
            <div
              key={i}
              className="mb-2 rounded-lg bg-[#1a1a1a] p-3"
              style={{ borderLeft: `3px solid ${severityColor[s.severity] || '#666'}` }}
            >
              <div
                className="mb-1 text-[14px] font-semibold"
                style={{ color: severityColor[s.severity] }}
              >
                [{s.severity.toUpperCase()}] {s.title}
              </div>
              <div className="text-[13px] text-[#aaa]">{s.detail}</div>
            </div>
          ))}

          {analysisReport && (
            <div className="mt-4 rounded-lg border border-[#333] bg-[#1a1a1a] p-4">
              <h4 className="mb-2 mt-0 text-[#00C9A7]">AI 优化报告</h4>
              <div className="whitespace-pre-wrap text-[13px] text-[#ccc]">
                {analysisReport}
              </div>
            </div>
          )}
        </div>

        {/* Trace 列表 */}
        <div className="card">
          <h3 className="mb-3 mt-0 text-white">最近调用记录</h3>
          {loading && <div className="text-[#666]">加载中...</div>}
          {!loading && traces.length === 0 && (
            <div className="text-sm text-[#666]">暂无 Trace 数据</div>
          )}
          {traces.map(t => (
            <div
              key={t.id}
              className="flex items-center gap-3 border-b border-[#222] py-2.5 text-[13px]"
            >
              <span className="w-20 font-mono text-[11px] text-[#888]">
                {t.id.slice(0, 8)}
              </span>
              <span className="flex-1 text-[#ccc]">{t.name}</span>
              <span className="w-[100px] text-[#888]">{t.model || '-'}</span>
              <span
                className="w-[60px]"
                style={{ color: t.status === 'success' ? '#00C9A7' : '#FF4757' }}
              >
                {t.status}
              </span>
              <span className="w-[70px] text-[#FFB800]">
                {t.latency_ms ? `${Math.round(t.latency_ms)}ms` : '-'}
              </span>
              <span className="w-[60px] text-[#00D4FF]">{t.tokens} tok</span>
              <span className="w-[70px] text-[#00C9A7]">
                ${(t.cost || 0).toFixed(4)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
