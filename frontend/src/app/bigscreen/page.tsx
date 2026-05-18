'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useHealthStore } from '@/lib/stores/health-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';
import { v } from '@/lib/utils';

const yearlyToChart = (yearly: Record<string, { distance: number; count: number }> | undefined) =>
  yearly
    ? Object.entries(yearly)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([year, val]) => ({ name: year, value: Math.round((val.distance ?? 0) / 1000) }))
    : [];

export default function BigscreenPage() {
  const { data, fetchDashboard } = useHealthStore();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    fetchDashboard();
    return () => clearTimeout(t);
  }, [fetchDashboard]);

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];
  const chartData = yearlyToChart(data['activity_summary.yearly']);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header title="数据大屏" activePath="/bigscreen" maxWidth="1400px" showDate={mounted} />

      <main style={{ padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
        {/* KPI Grid */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>核心指标</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
            <KpiCard title="VO2 Max" value={v(data['profile.vo2_max'])} unit="ml/kg/min" status="excellent" />
            <KpiCard title="BMI" value={v(data['profile.bmi'])} status="good" />
            <KpiCard title="体重" value={v(data['profile.weight_kg'])} unit="kg" status="good" />
            <KpiCard title="训练准备度" value={v(training?.readiness_score)} unit="/100" status={typeof training?.readiness_score === 'number' && training.readiness_score >= 60 ? 'good' : 'warning'} />
            <KpiCard title="ACWR" value={v(training?.acwr)} status={typeof training?.acwr === 'number' && training.acwr >= 0.8 && training.acwr <= 1.3 ? 'good' : 'warning'} />
            <KpiCard title="日均睡眠" value={v(sleep?.avg_total_hours)} unit="h" status="good" />
          </div>
        </section>

        {/* Charts Row */}
        <section style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>
              年度跑量 <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>km</span>
            </h3>
            <LineChart data={chartData} height={240} unit="km" />
          </div>

          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>训练状态</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <MetricRow label="耐力评分" value={v(training?.endurance_score)} color="var(--primary)" />
              <MetricRow label="爬坡评分" value={v(training?.hill_score)} color="var(--secondary)" />
              <MetricRow label="深睡占比" value={`${v(sleep?.deep_pct)}%`} color="var(--accent)" />
              <MetricRow label="总跑量" value={running?.total_km != null ? `${running.total_km.toFixed(0)} km` : '-'} color="var(--warning)" />
            </div>
          </div>
        </section>

        {/* Action Links */}
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
          <Link href="/dashboard" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📊</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>仪表盘</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康数据</div>
            </div>
          </Link>
          <Link href="/report" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📋</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>AI 报告</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康分析</div>
            </div>
          </Link>
          <div className="card" style={{ opacity: 0.5 }}>
            <span style={{ fontSize: '20px' }}>🗺️</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>运动轨迹</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>即将推出</div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricRow({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{label}</div>
      <div style={{ fontSize: '24px', fontWeight: '600', color }}>{value}</div>
    </div>
  );
}
