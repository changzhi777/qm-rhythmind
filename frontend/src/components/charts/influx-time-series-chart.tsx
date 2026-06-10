'use client';

import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { api, type InfluxTimeSeriesResponse } from '@/lib/api';

interface InfluxTimeSeriesChartProps {
  metric: string;                  // heart_rate_avg, steps, sleep_hours, hrv ...
  metricLabel?: string;            // 显示标签
  range?: string;                  // -7d, -30d ...
  aggregation?: string;            // 1d, 1h, 1w
  fn?: 'mean' | 'max' | 'min' | 'last';
  color?: string;                  // hex 颜色
  height?: number;
}

const DEFAULT_COLOR = '#00C9A7';

type FetchState =
  | { kind: 'loading' }
  | { kind: 'ok'; data: InfluxTimeSeriesResponse }
  | { kind: 'empty'; message?: string };

export function InfluxTimeSeriesChart({
  metric,
  metricLabel,
  range = '-7d',
  aggregation = '1d',
  fn = 'mean',
  color = DEFAULT_COLOR,
  height = 240,
}: InfluxTimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [state, setState] = useState<FetchState>({ kind: 'loading' });

  // 1. 数据获取（loading 状态由初始 useState 表达，避免 effect 中 setState）
  useEffect(() => {
    let cancelled = false;
    api.getInfluxTimeSeries(metric, range, aggregation, fn)
      .then((res) => {
        if (cancelled) return;
        if (res.status === 'ok' && res.data.length > 0) {
          setState({ kind: 'ok', data: res });
        } else {
          setState({ kind: 'empty', message: res.error || '暂无时序数据' });
        }
      })
      .catch(() => {
        if (cancelled) return;
        setState({ kind: 'empty', message: '加载失败' });
      });
    return () => { cancelled = true; };
  }, [metric, range, aggregation, fn]);

  // 2. ECharts 初始化（仅 mount 一次）
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, 'dark');
    chartRef.current = chart;
    const handleResize = () => chart?.resize();
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart?.dispose();
      chartRef.current = null;
    };
  }, []);

  // 3. 数据变化时 setOption
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (state.kind !== 'ok') {
      chart.clear();
      return;
    }

    const data = state.data;
    chart.setOption({
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(26,26,26,0.9)',
        borderColor: '#333',
        textStyle: { color: '#fff' },
      },
      grid: { left: '10%', right: '5%', top: '12%', bottom: '10%' },
      xAxis: {
        type: 'category' as const,
        data: data.data.map(d => d.ts.substring(0, 10)),
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 11 },
      },
      yAxis: {
        type: 'value' as const,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 11 },
        splitLine: { lineStyle: { color: '#333', type: 'dashed' } },
      },
      series: [{
        name: metricLabel || metric,
        type: 'line',
        data: data.data.map(d => d.value),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color, width: 2 },
        itemStyle: { color },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: color + '33' },
            { offset: 1, color: color + '05' },
          ]),
        },
      }],
    });
  }, [state, color, metric, metricLabel]);

  return (
    <div style={{ position: 'relative' }}>
      <div ref={containerRef} style={{ width: '100%', height: `${height}px` }} />
      {state.kind === 'loading' && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'rgba(17,17,17,0.6)', color: 'var(--text-muted)', fontSize: 12,
        }}>
          加载中...
        </div>
      )}
      {state.kind === 'empty' && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: 'var(--text-muted)', fontSize: 13,
        }}>
          {state.message}
        </div>
      )}
    </div>
  );
}
