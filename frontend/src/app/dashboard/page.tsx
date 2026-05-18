'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useHealthStore } from '@/lib/stores/health-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';
import { v, formatPace } from '@/lib/utils';

const yearlyToChart = (yearly: Record<string, { distance: number; count: number }> | undefined) =>
  yearly
    ? Object.entries(yearly)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([year, val]) => ({ name: year, value: Math.round((val.distance ?? 0) / 1000) }))
    : [];

export default function DashboardPage() {
  const { data, fetchDashboard } = useHealthStore();

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];
  const yearlyChart = yearlyToChart(data['activity_summary.yearly']);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      <Header title="健康仪表盘" activePath="/dashboard" />

      <main style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
        {/* Profile KPIs */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>基本信息</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <KpiCard title="VO2 Max" value={v(data['profile.vo2_max'])} unit="ml/kg/min" status="excellent" />
            <KpiCard title="BMI" value={v(data['profile.bmi'])} status="good" />
            <KpiCard title="体重" value={v(data['profile.weight_kg'])} unit="kg" status="good" />
            <KpiCard title="年龄" value={v(data['profile.age'])} unit="岁" status="good" />
          </div>
        </section>

        {/* Training KPIs */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>训练状态</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <KpiCard title="训练准备度" value={v(training?.readiness_score)} unit="/100" status={typeof training?.readiness_score === 'number' && training.readiness_score >= 60 ? 'good' : 'warning'} />
            <KpiCard title="ACWR" value={v(training?.acwr)} status={typeof training?.acwr === 'number' && training.acwr >= 0.8 && training.acwr <= 1.3 ? 'good' : 'warning'} />
            <KpiCard title="耐力评分" value={v(training?.endurance_score)} status="excellent" />
            <KpiCard title="爬坡评分" value={v(training?.hill_score)} status="good" />
          </div>
        </section>

        {/* Running & Sleep */}
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>跑步数据</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <DataCell label="总跑量" value={running?.total_km != null ? running.total_km.toFixed(1) : '-'} unit="km" color="var(--primary)" />
              <DataCell label="跑步次数" value={v(running?.total_runs)} color="var(--secondary)" />
              <DataCell label="平均配速" value={formatPace(running?.avg_pace_min_per_km)} unit="/km" color="var(--accent)" />
              <DataCell label="静息心率" value={v(data['profile.resting_hr'])} unit="bpm" color="var(--warning)" />
            </div>
          </div>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>睡眠数据</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <DataCell label="平均时长" value={v(sleep?.avg_total_hours)} unit="h" color="var(--primary)" />
              <DataCell label="深睡占比" value={v(sleep?.deep_pct)} unit="%" color="var(--secondary)" />
              <DataCell label="深睡时长" value={v(sleep?.avg_deep_hours)} unit="h" color="var(--accent)" />
              <DataCell label="记录天数" value={v(sleep?.record_days)} unit="天" color="var(--text-secondary)" />
            </div>
          </div>
        </section>

        {/* Yearly Chart */}
        <section style={{ marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>年度跑量趋势 <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>km</span></h3>
            <LineChart data={yearlyChart} height={220} color="var(--primary)" unit="km" />
          </div>
        </section>

        {/* Navigation */}
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '12px' }}>
          <Link href="/bigscreen" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📊</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>数据大屏</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>全屏展示</div>
            </div>
          </Link>
          <Link href="/report" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📋</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>AI 健康报告</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>查看详情</div>
            </div>
          </Link>
        </section>
      </main>
    </div>
  );
}

function DataCell({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: '600', color }}>
        {value}{unit && <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}> {unit}</span>}
      </div>
    </div>
  );
}
