'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

interface LineChartProps {
  title?: string;
  data: { name: string; value: number }[];
  height?: number;
  color?: string;
  unit?: string;
}

const COLOR_MAP: Record<string, string> = {
  'var(--primary)': '#00C9A7',
  'var(--secondary)': '#00A99D',
  'var(--accent)': '#00D4FF',
};

export function LineChart({ title, data, height = 300, color = 'var(--primary)', unit = '' }: LineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const resolvedColor = COLOR_MAP[color] || color;

  useEffect(() => {
    if (!containerRef.current) return;

    let chart = chartRef.current;
    if (!chart) {
      chart = echarts.init(containerRef.current, 'dark');
      chartRef.current = chart;

      const handleResize = () => chart?.resize();
      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        chart?.dispose();
        chartRef.current = null;
      };
    }
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !containerRef.current) return;

    if (data.length === 0) {
      chart.clear();
      return;
    }

    chart.setOption({
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
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: resolvedColor + '33' },
            { offset: 1, color: resolvedColor + '05' },
          ]),
        },
      }],
    });
  }, [data, title, resolvedColor, unit]);

  return <div ref={containerRef} style={{ width: '100%', height: `${height}px` }} />;
}
