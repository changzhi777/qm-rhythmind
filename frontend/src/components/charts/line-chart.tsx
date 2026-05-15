// 折线趋势图组件 — 扁平化

'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

interface LineChartProps {
  title?: string;
  data: { name: string; value: number }[];
  height?: number;
  color?: string;
}

const COLOR_MAP: Record<string, string> = {
  'var(--primary)': '#00C9A7',
  'var(--secondary)': '#00A99D',
  'var(--accent)': '#00D4FF',
};

function resolveColor(color: string): string {
  return COLOR_MAP[color] || color;
}

export function LineChart({ title, data, height = 300, color = 'var(--primary)' }: LineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  const resolvedColor = resolveColor(color);

  useEffect(() => {
    if (!chartRef.current) return;
    chartInstance.current = echarts.init(chartRef.current, 'dark');

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartInstance.current) return;

    const option = {
      backgroundColor: 'transparent',
      title: title ? { text: title, textStyle: { color: '#fff', fontSize: 14 } } : undefined,
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(26,26,26,0.9)',
        borderColor: '#333',
        textStyle: { color: '#fff' },
      },
      grid: { left: '10%', right: '5%', top: title ? '15%' : '5%', bottom: '10%' },
      xAxis: {
        type: 'category',
        data: data.map(d => d.name),
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 12 },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#888', fontSize: 12 },
        splitLine: { lineStyle: { color: '#333', type: 'dashed' } },
      },
      series: [{
        type: 'line',
        data: data.map(d => d.value),
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: resolvedColor, width: 2 },
        itemStyle: { color: resolvedColor },
      }],
    };

    chartInstance.current.setOption(option);
  }, [data, title, resolvedColor]);

  return <div ref={chartRef} style={{ width: '100%', height: `${height}px` }} />;
}