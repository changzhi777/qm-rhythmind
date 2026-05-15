// 数据大屏页面 — 扁平化设计

'use client';

import { useEffect } from 'react';
import { useHealthStore } from '@/lib/stores/health-store';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';

export default function BigscreenPage() {
  const { data, fetchDashboard } = useHealthStore();

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const profile = {
    vo2_max: data['profile.vo2_max'],
    bmi: data['profile.bmi'],
    weight_kg: data['profile.weight_kg'],
  };

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];

  const yearlyData = data['activity_summary.yearly'];
  const chartData = yearlyData
    ? Object.entries(yearlyData).map(([year, val]) => ({
        name: year,
        value: Math.round((val.distance || 0) / 100000),
      }))
    : [];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      {/* Header */}
      <header style={{ borderBottom: '1px solid var(--border)', padding: '16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', maxWidth: '1400px', margin: '0 auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ color: 'white', fontWeight: '700', fontSize: '16px' }}>R</span>
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                <h1 style={{ fontSize: '18px', fontWeight: '600', color: 'white' }}>RHYTHMIND</h1>
                <span style={{ fontSize: '12px', color: 'var(--primary)', fontWeight: '500' }}>律动</span>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontWeight: '400' }}>v0.1.9</span>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>数据大屏</p>
            </div>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {new Date().toLocaleDateString('zh-CN')}
          </div>
        </div>
      </header>

      {/* Main */}
      <main style={{ padding: '24px', maxWidth: '1400px', margin: '0 auto' }}>
        {/* KPI Grid */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>核心指标</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '12px' }}>
            <KpiCard title="VO2 Max" value={profile.vo2_max || '-'} unit="ml/kg/min" status="good" />
            <KpiCard title="BMI" value={profile.bmi || '-'} status="good" />
            <KpiCard title="体重" value={profile.weight_kg || '-'} unit="kg" status="good" />
            <KpiCard title="训练准备度" value={training?.readiness_score || '-'} unit="/100" status="warning" />
            <KpiCard title="ACWR" value={training?.acwr || '-'} status="warning" />
            <KpiCard title="日均睡眠" value={sleep?.avg_total_hours || '-'} unit="h" status="good" />
          </div>
        </section>

        {/* Charts Row */}
        <section style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>年度跑量</h3>
            {chartData.length > 0 ? (
              <LineChart data={chartData} height={240} />
            ) : (
              <div style={{ height: '240px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                暂无数据
              </div>
            )}
          </div>

          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>训练状态</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>耐力评分</div>
                <div style={{ fontSize: '24px', fontWeight: '600', color: 'var(--primary)' }}>{training?.endurance_score || '-'}</div>
              </div>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>爬坡评分</div>
                <div style={{ fontSize: '24px', fontWeight: '600', color: 'var(--secondary)' }}>{training?.hill_score || '-'}</div>
              </div>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>深睡占比</div>
                <div style={{ fontSize: '24px', fontWeight: '600', color: 'var(--accent)' }}>{sleep?.deep_pct || '-'}%</div>
              </div>
            </div>
          </div>
        </section>

        {/* Action Links */}
        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
          <a href="/dashboard" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📊</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>仪表盘</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康数据</div>
            </div>
          </a>
          <a href="/report" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📋</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>AI 报告</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>健康分析</div>
            </div>
          </a>
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