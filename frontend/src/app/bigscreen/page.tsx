'use client';

// /bigscreen — 数据大屏(Stage 3:接入 8 组件 + 错误处理)
// 2026-06-24 frontend-polish Stage 3

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useHealthStore } from '@/lib/stores/health-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';
import { ErrorState, useToast } from '@/components/ui';
import { v, yearlyToChart } from '@/lib/utils';

export default function BigscreenPage() {
  const { data, loading, error, fetchDashboard } = useHealthStore();
  const [mounted, setMounted] = useState(false);
  const toast = useToast();

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    fetchDashboard().catch((e: unknown) =>
      toast.error(`大屏加载失败: ${e instanceof Error ? e.message : e}`),
    );
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];
  const chartData = yearlyToChart(data['activity_summary.yearly']);

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="数据大屏" activePath="/bigscreen" maxWidth="1400px" showDate={mounted} />

      <main className="mx-auto max-w-[1400px] p-6">
        {error && !loading ? (
          <ErrorState error={error} onRetry={() => fetchDashboard()} />
        ) : null}
        {/* KPI Grid */}
        <section className="mb-6">
          <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
            核心指标
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
            <KpiCard title="VO2 Max" value={v(data['profile.vo2_max'])} unit="ml/kg/min" status="excellent" />
            <KpiCard title="BMI" value={v(data['profile.bmi'])} status="good" />
            <KpiCard title="体重" value={v(data['profile.weight_kg'])} unit="kg" status="good" />
            <KpiCard title="训练准备度" value={v(training?.readiness_score)} unit="/100" status={typeof training?.readiness_score === 'number' && training.readiness_score >= 60 ? 'good' : 'concerned'} />
            <KpiCard title="ACWR" value={v(training?.acwr)} status={typeof training?.acwr === 'number' && training.acwr >= 0.8 && training.acwr <= 1.3 ? 'good' : 'concerned'} />
            <KpiCard title="日均睡眠" value={v(sleep?.avg_total_hours)} unit="h" status="good" />
          </div>
        </section>

        {/* Charts Row */}
        <section className="mb-6 grid grid-cols-[2fr_1fr] gap-4">
          <div className="card">
            <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-4">
              年度跑量 <span className="text-[11px] font-normal text-[var(--text-muted)]">km</span>
            </h3>
            <LineChart data={chartData} height={240} unit="km" />
          </div>

          <div className="card">
            <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-4">训练状态</h3>
            <div className="flex flex-col gap-3">
              <MetricRow label="耐力评分" value={v(training?.endurance_score)} color="var(--primary)" />
              <MetricRow label="爬坡评分" value={v(training?.hill_score)} color="var(--secondary)" />
              <MetricRow label="深睡占比" value={`${v(sleep?.deep_pct)}%`} color="var(--accent)" />
              <MetricRow label="总跑量" value={running?.total_km != null ? `${running.total_km.toFixed(0)} km` : '-'} color="var(--warning)" />
            </div>
          </div>
        </section>

        {/* Action Links */}
        <section className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
          <Link href="/dashboard" className="card">
            <span className="text-xl">📊</span>
            <div>
              <div className="text-sm font-medium text-white">仪表盘</div>
              <div className="text-xs text-[var(--text-muted)]">健康数据</div>
            </div>
          </Link>
          <Link href="/report" className="card">
            <span className="text-xl">📋</span>
            <div>
              <div className="text-sm font-medium text-white">AI 报告</div>
              <div className="text-xs text-[var(--text-muted)]">健康分析</div>
            </div>
          </Link>
          <div className="card opacity-50">
            <span className="text-xl">🗺️</span>
            <div>
              <div className="text-sm font-medium text-white">运动轨迹</div>
              <div className="text-xs text-[var(--text-muted)]">即将推出</div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricRow({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div className="rounded-md bg-[var(--surface-elevated)] p-3">
      <div className="text-[11px] text-[var(--text-muted)] mb-1">{label}</div>
      <div className="text-2xl font-semibold" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
