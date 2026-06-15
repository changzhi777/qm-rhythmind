'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useHealthStore } from '@/lib/stores/health-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';
import { InfluxTimeSeriesChart } from '@/components/charts/influx-time-series-chart';
import { Skeleton } from '@/components/ui/skeleton';
import { useAutoRefresh } from '@/lib/hooks/use-auto-refresh';
import { v, formatPace, yearlyToChart } from '@/lib/utils';

// 时序趋势图可切换的指标 Tab
const SERIES_TABS: { key: string; label: string }[] = [
  { key: 'heart_rate_avg', label: '心率' },
  { key: 'hrv', label: 'HRV' },
  { key: 'steps', label: '步数' },
  { key: 'sleep_hours', label: '睡眠' },
];

export default function DashboardPage() {
  const { data, loading, fetchDashboard } = useHealthStore();
  const [activeSeries, setActiveSeries] = useState<string>('heart_rate_avg');

  useEffect(() => { fetchDashboard(); }, [fetchDashboard]);
  useAutoRefresh(60_000, fetchDashboard);

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];
  const yearlyChart = yearlyToChart(data['activity_summary.yearly']);
  const activeSeriesLabel = SERIES_TABS.find(t => t.key === activeSeries)?.label ?? activeSeries;

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="健康仪表盘" activePath="/dashboard" />

      <main className="mx-auto max-w-[1200px] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-white">健康仪表盘</h1>
          <button
            onClick={() => fetchDashboard()}
            disabled={loading}
            className="cursor-pointer rounded-md border border-[var(--border)] text-xs px-3.5 py-1.5 bg-[var(--surface)] text-[var(--text-secondary)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? '刷新中...' : '🔄 刷新'}
          </button>
        </div>

        {/* Profile KPIs */}
        <section className="mb-6">
          <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
            基本信息
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
            {loading ? (
              <>
                <Skeleton height={80} />
                <Skeleton height={80} />
                <Skeleton height={80} />
                <Skeleton height={80} />
              </>
            ) : (
              <>
                <KpiCard title="VO2 Max" value={v(data['profile.vo2_max'])} unit="ml/kg/min" status="excellent" />
                <KpiCard title="BMI" value={v(data['profile.bmi'])} status="good" />
                <KpiCard title="体重" value={v(data['profile.weight_kg'])} unit="kg" status="good" />
                <KpiCard title="年龄" value={v(data['profile.age'])} unit="岁" status="good" />
              </>
            )}
          </div>
        </section>

        {/* Training KPIs */}
        <section className="mb-6">
          <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
            训练状态
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
            <KpiCard title="训练准备度" value={v(training?.readiness_score)} unit="/100" status={typeof training?.readiness_score === 'number' && training.readiness_score >= 60 ? 'good' : 'warning'} />
            <KpiCard title="ACWR" value={v(training?.acwr)} status={typeof training?.acwr === 'number' && training.acwr >= 0.8 && training.acwr <= 1.3 ? 'good' : 'warning'} />
            <KpiCard title="耐力评分" value={v(training?.endurance_score)} status="excellent" />
            <KpiCard title="爬坡评分" value={v(training?.hill_score)} status="good" />
          </div>
        </section>

        {/* Running & Sleep */}
        <section className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(400px,1fr))] gap-4">
          <div className="card">
            <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-4">跑步数据</h3>
            <div className="grid grid-cols-2 gap-3">
              <DataCell label="总跑量" value={running?.total_km != null ? running.total_km.toFixed(1) : '-'} unit="km" color="var(--primary)" />
              <DataCell label="跑步次数" value={v(running?.total_runs)} color="var(--secondary)" />
              <DataCell label="平均配速" value={formatPace(running?.avg_pace_min_per_km)} unit="/km" color="var(--accent)" />
              <DataCell label="静息心率" value={v(data['profile.resting_hr'])} unit="bpm" color="var(--warning)" />
            </div>
          </div>
          <div className="card">
            <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-4">睡眠数据</h3>
            <div className="grid grid-cols-2 gap-3">
              <DataCell label="平均时长" value={v(sleep?.avg_total_hours)} unit="h" color="var(--primary)" />
              <DataCell label="深睡占比" value={v(sleep?.deep_pct)} unit="%" color="var(--secondary)" />
              <DataCell label="深睡时长" value={v(sleep?.avg_deep_hours)} unit="h" color="var(--accent)" />
              <DataCell label="记录天数" value={v(sleep?.record_days)} unit="天" color="var(--text-secondary)" />
            </div>
          </div>
        </section>

        {/* Yearly Chart */}
        <section className="mb-6">
          <div className="card">
            <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-4">
              年度跑量趋势{' '}
              <span className="text-[11px] font-normal text-[var(--text-muted)]">km</span>
            </h3>
            <LineChart data={yearlyChart} height={220} color="var(--primary)" unit="km" />
          </div>
        </section>

        {/* InfluxDB 时序趋势 */}
        <section className="mb-6">
          <div className="card">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--text-secondary)]">
                时序趋势{' '}
                <span className="ml-2 text-[11px] font-normal text-[var(--text-muted)]">
                  InfluxDB · 7天
                </span>
              </h3>
              <div className="flex gap-1">
                {SERIES_TABS.map(t => {
                  const active = activeSeries === t.key;
                  return (
                    <button
                      key={t.key}
                      onClick={() => setActiveSeries(t.key)}
                      className={`cursor-pointer rounded px-2.5 py-1 text-[11px] font-medium border-none ${active ? 'bg-[var(--primary)] text-[#111]' : 'bg-[var(--surface-elevated)] text-[var(--text-secondary)]'}`}
                    >
                      {t.label}
                    </button>
                  );
                })}
              </div>
            </div>
            <InfluxTimeSeriesChart
              metric={activeSeries}
              metricLabel={activeSeriesLabel}
              range="-7d"
              aggregation="1d"
              color="#00C9A7"
              height={240}
            />
          </div>
        </section>

        {/* Navigation */}
        <section className="grid grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-3">
          <Link
            href="/bigscreen"
            className="card"
          >
            <span className="text-xl">📊</span>
            <div>
              <div className="text-sm font-medium text-white">数据大屏</div>
              <div className="text-xs text-[var(--text-muted)]">全屏展示</div>
            </div>
          </Link>
          <Link
            href="/report"
            className="card"
          >
            <span className="text-xl">📋</span>
            <div>
              <div className="text-sm font-medium text-white">AI 健康报告</div>
              <div className="text-xs text-[var(--text-muted)]">查看详情</div>
            </div>
          </Link>
        </section>
      </main>
    </div>
  );
}

function DataCell({ label, value, unit, color }: { label: string; value: string | number; unit?: string; color: string }) {
  return (
    <div className="rounded-md bg-[var(--surface-elevated)] p-3">
      <div className="text-[11px] text-[var(--text-muted)] mb-1">{label}</div>
      <div className="text-xl font-semibold" style={{ color }}>
        {value}
        {unit && <span className="text-xs text-[var(--text-muted)]"> {unit}</span>}
      </div>
    </div>
  );
}
