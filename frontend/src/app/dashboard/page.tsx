'use client';

// /dashboard — 健康仪表盘(Stage 1.1-1.6:组件接入 + 阈值 + 时间窗口 + 目标 + 同比 + 钻取)
// 2026-06-24 frontend-polish Stage 1

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useHealthStore } from '@/lib/stores/health-store';
import { Header } from '@/components/layout/header';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';
import { InfluxTimeSeriesChart } from '@/components/charts/influx-time-series-chart';
import {
  Button,
  Card,
  ErrorState,
  Modal,
  Skeleton,
  Tabs,
  useToast,
  type TabItem,
} from '@/components/ui';
import { useAutoRefresh } from '@/lib/hooks/use-auto-refresh';
import { v, formatPace, yearlyToChart } from '@/lib/utils';
import {
  DEFAULT_THRESHOLDS,
  evaluateKpi,
  loadThresholdOverrides,
  applyOverrides,
} from '@/lib/kpi-thresholds';

// 时序趋势图可切换的指标 Tab
const SERIES_TABS: TabItem[] = [
  { key: 'heart_rate_avg', label: '心率' },
  { key: 'hrv', label: 'HRV' },
  { key: 'steps', label: '步数' },
  { key: 'sleep_hours', label: '睡眠' },
];

// Stage 1.3: 时间窗口选项
const TIME_RANGES: { key: string; label: string; range: string; agg: string }[] = [
  { key: '7d', label: '7天', range: '-7d', agg: '1d' },
  { key: '30d', label: '30天', range: '-30d', agg: '1d' },
  { key: '90d', label: '90天', range: '-90d', agg: '7d' },
  { key: '365d', label: '1年', range: '-365d', agg: '30d' },
];

export default function DashboardPage() {
  const { data, loading, error, fetchDashboard } = useHealthStore();
  const [activeSeries, setActiveSeries] = useState<string>('heart_rate_avg');
  const [timeRange, setTimeRange] = useState<string>('7d');
  const [drillDown, setDrillDown] = useState<{ title: string; value: string | number; unit?: string } | null>(null);
  const toast = useToast();

  // Stage 1.2: 应用用户阈值覆写
  const thresholds = applyOverrides(DEFAULT_THRESHOLDS, loadThresholdOverrides());

  const activeRange = TIME_RANGES.find((r) => r.key === timeRange) ?? TIME_RANGES[0];

  // 优化 #6: useCallback 工厂消除内联箭头函数导致 KpiCard 不必要 re-render
  const drill = useCallback(
    (title: string, value: string | number, unit?: string) =>
      () => setDrillDown({ title, value, unit }),
    [],
  );

  useEffect(() => {
    fetchDashboard().catch((e: unknown) => {
      const msg = e instanceof Error ? e.message : '加载失败';
      toast.error(`仪表盘加载失败: ${msg}`);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useAutoRefresh(60_000, async () => {
    try {
      await fetchDashboard();
    } catch (e) {
      // 自动刷新静默失败,不打扰用户
      console.warn('[auto-refresh] dashboard failed', e);
    }
  });

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];
  const yearlyChart = yearlyToChart(data['activity_summary.yearly']);
  const activeSeriesLabel = SERIES_TABS.find((t) => t.key === activeSeries)?.label ?? activeSeries;
  const hasData = Object.keys(data).length > 0;

  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="健康仪表盘" activePath="/dashboard" />

      <main className="mx-auto max-w-[1200px] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-white">健康仪表盘</h1>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              fetchDashboard()
                .then(() => toast.success('刷新成功'))
                .catch((e: unknown) => toast.error(`刷新失败: ${e instanceof Error ? e.message : e}`))
            }
            loading={loading}
          >
            🔄 刷新
          </Button>
        </div>

        {/* 错误托盘(全局 + 页面 ErrorState 双层) */}
        {error && !loading ? (
          <div className="mb-6">
            <ErrorState error={error} onRetry={() => fetchDashboard()} compact />
          </div>
        ) : null}

        {/* Profile KPIs */}
        <section className="mb-6">
          <h2 className="text-[13px] font-medium uppercase tracking-wider text-[var(--text-muted)] mb-3">
            基本信息
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
            {loading && !hasData ? (
              <>
                <Skeleton height={80} />
                <Skeleton height={80} />
                <Skeleton height={80} />
                <Skeleton height={80} />
              </>
            ) : (
              <>
                <KpiCard
                  title="VO2 Max"
                  value={v(data['profile.vo2_max'])}
                  unit="ml/kg/min"
                  status={evaluateKpi(data['profile.vo2_max'] as number | undefined, thresholds.vo2_max) ?? 'good'}
                  icon={<DrillButton onClick={drill('VO2 Max', v(data['profile.vo2_max']), 'ml/kg/min')} />}
                />
                <KpiCard
                  title="BMI"
                  value={v(data['profile.bmi'])}
                  status={evaluateKpi(data['profile.bmi'] as number | undefined, thresholds.bmi) ?? 'good'}
                  icon={<DrillButton onClick={drill('BMI', v(data['profile.bmi']))} />}
                />
                <KpiCard
                  title="体重"
                  value={v(data['profile.weight_kg'])}
                  unit="kg"
                  status="good"
                  icon={<DrillButton onClick={drill('体重', v(data['profile.weight_kg']), 'kg')} />}
                />
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
            <KpiCard
              title="训练准备度"
              value={v(training?.readiness_score)}
              unit="/100"
              status={evaluateKpi(training?.readiness_score, thresholds.readiness_score) ?? 'good'}
            />
            <KpiCard
              title="ACWR"
              value={v(training?.acwr)}
              status={evaluateKpi(training?.acwr, thresholds.acwr) ?? 'good'}
            />
            <KpiCard title="耐力评分" value={v(training?.endurance_score)} status="excellent" />
            <KpiCard title="爬坡评分" value={v(training?.hill_score)} status="good" />
          </div>
        </section>

        {/* Running & Sleep */}
        <section className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(400px,1fr))] gap-4">
          <Card title="跑步数据">
            <div className="grid grid-cols-2 gap-3">
              <DataCell label="总跑量" value={running?.total_km != null ? running.total_km.toFixed(1) : '-'} unit="km" color="var(--primary)" />
              <DataCell label="跑步次数" value={v(running?.total_runs)} color="var(--secondary)" />
              <DataCell label="平均配速" value={formatPace(running?.avg_pace_min_per_km)} unit="/km" color="var(--accent)" />
              <DataCell label="静息心率" value={v(data['profile.resting_hr'])} unit="bpm" color="var(--warning)" />
            </div>
          </Card>
          <Card title="睡眠数据">
            <div className="grid grid-cols-2 gap-3">
              <DataCell label="平均时长" value={v(sleep?.avg_total_hours)} unit="h" color="var(--primary)" />
              <DataCell label="深睡占比" value={v(sleep?.deep_pct)} unit="%" color="var(--secondary)" />
              <DataCell label="深睡时长" value={v(sleep?.avg_deep_hours)} unit="h" color="var(--accent)" />
              <DataCell label="记录天数" value={v(sleep?.record_days)} unit="天" color="var(--text-secondary)" />
            </div>
          </Card>
        </section>

        {/* Yearly Chart */}
        <section className="mb-6">
          <Card title="年度跑量趋势">
            <span className="text-[11px] font-normal text-[var(--text-muted)]">km</span>
            <LineChart data={yearlyChart} height={220} color="var(--primary)" unit="km" />
          </Card>
        </section>

        {/* InfluxDB 时序趋势 */}
        <section className="mb-6">
          <Card
            title={
              <span className="flex items-center gap-2">
                时序趋势
                <span className="text-[11px] font-normal text-[var(--text-muted)]">InfluxDB · {activeRange.label}</span>
              </span>
            }
            footer={
              // 优化 #10:复用 Tabs 组件,统一 a11y/键盘支持
              <Tabs
                tabs={TIME_RANGES.map((r) => ({ key: r.key, label: r.label }))}
                active={timeRange}
                onChange={setTimeRange}
              />
            }
          >
            <div className="mb-4">
              <Tabs tabs={SERIES_TABS} active={activeSeries} onChange={setActiveSeries} />
            </div>
            <InfluxTimeSeriesChart
              metric={activeSeries}
              metricLabel={activeSeriesLabel}
              range={activeRange.range}
              aggregation={activeRange.agg}
              color="#00C9A7"
              height={240}
            />
          </Card>
        </section>

        {/* Stage 1.6: KPI 钻取 Modal */}
        {drillDown ? (
          <Modal
            open={!!drillDown}
            onClose={() => setDrillDown(null)}
            title={`${drillDown.title} 详情`}
            size="md"
            footer={
              <Button variant="secondary" onClick={() => setDrillDown(null)}>
                关闭
              </Button>
            }
          >
            <div className="space-y-4">
              <div className="text-center py-6">
                <div className="text-4xl font-semibold text-[var(--primary)]">
                  {drillDown.value}
                  {drillDown.unit ? (
                    <span className="text-base text-[var(--text-muted)] ml-1">{drillDown.unit}</span>
                  ) : null}
                </div>
                <div className="text-sm text-[var(--text-secondary)] mt-2">{drillDown.title}</div>
              </div>
              <div className="border-t border-[var(--border)] pt-4 space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--text-muted)]">当前阈值</span>
                  <span>参考 DEFAULT_THRESHOLDS</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-muted)]">趋势(7天)</span>
                  <span>可在时序图中查看</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-muted)]">历史最高</span>
                  <span>暂未跟踪</span>
                </div>
              </div>
              <div className="bg-[var(--surface-elevated)] p-3 rounded text-xs text-[var(--text-secondary)]">
                💡 详细分析可在 <Link href="/report" className="text-[var(--primary)] underline">AI 健康报告</Link> 中查看
              </div>
            </div>
          </Modal>
        ) : null}

        {/* Navigation */}
        <section className="grid grid-cols-[repeat(auto-fit,minmax(250px,1fr))] gap-3">
          <Link href="/bigscreen" className="contents">
            <Card interactive>
              <div className="flex items-center gap-3">
                <span className="text-2xl" aria-hidden="true">📊</span>
                <div>
                  <div className="text-sm font-medium text-white">数据大屏</div>
                  <div className="text-xs text-[var(--text-muted)]">全屏展示</div>
                </div>
              </div>
            </Card>
          </Link>
          <Link href="/report" className="contents">
            <Card interactive>
              <div className="flex items-center gap-3">
                <span className="text-2xl" aria-hidden="true">📋</span>
                <div>
                  <div className="text-sm font-medium text-white">AI 健康报告</div>
                  <div className="text-xs text-[var(--text-muted)]">查看详情</div>
                </div>
              </div>
            </Card>
          </Link>
        </section>
      </main>
    </div>
  );
}

function DataCell({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: string | number;
  unit?: string;
  color: string;
}) {
  return (
    <div className="rounded-md bg-[var(--surface-elevated)] p-3">
      <div className="text-[11px] text-[var(--text-muted)] mb-1">{label}</div>
      <div className="text-xl font-semibold" style={{ color }}>
        {value}
        {unit ? <span className="text-xs text-[var(--text-muted)]"> {unit}</span> : null}
      </div>
    </div>
  );
}

function DrillButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="查看详情"
      className="text-xs text-[var(--text-muted)] hover:text-[var(--primary)] transition-colors"
    >
      🔍
    </button>
  );
}