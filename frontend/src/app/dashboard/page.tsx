// 仪表盘页面 — 扁平化设计

'use client';

import { useEffect } from 'react';
import { useHealthStore } from '@/lib/stores/health-store';
import { KpiCard } from '@/components/dashboard/kpi-card';
import { LineChart } from '@/components/charts/line-chart';

export default function DashboardPage() {
  const { data, fetchDashboard } = useHealthStore();

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  const profile = {
    vo2_max: data['profile.vo2_max'],
    age: data['profile.age'],
    bmi: data['profile.bmi'],
    weight_kg: data['profile.weight_kg'],
  };

  const training = data['training.metrics'];
  const sleep = data['sleep.summary'];
  const running = data['running.summary'];

  const weeklyData = [
    { name: '周一', value: 5.2 },
    { name: '周二', value: 3.8 },
    { name: '周三', value: 6.1 },
    { name: '周四', value: 4.5 },
    { name: '周五', value: 7.2 },
    { name: '周六', value: 10.5 },
    { name: '周日', value: 8.3 },
  ];

  const monthlyData = [
    { name: '1月', value: 45 },
    { name: '2月', value: 52 },
    { name: '3月', value: 48 },
    { name: '4月', value: 61 },
    { name: '5月', value: 55 },
    { name: '6月', value: 68 },
  ];

  return (
    <div style={{ minHeight: '100vh', background: 'var(--background)' }}>
      {/* Header */}
      <header style={{ borderBottom: '1px solid var(--border)', padding: '16px 24px' }}>
        <div style={{ maxWidth: '1200px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
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
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>健康仪表盘</p>
            </div>
          </div>
          <nav style={{ display: 'flex', gap: '24px' }}>
            <a href="/dashboard" style={{ fontSize: '13px', color: 'var(--primary)', fontWeight: '500' }}>仪表盘</a>
            <a href="/bigscreen" style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>大屏</a>
            <a href="/report" style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>报告</a>
          </nav>
        </div>
      </header>

      {/* Main */}
      <main style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
        {/* Profile KPIs */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>基本信息</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
            <KpiCard title="VO2 Max" value={profile.vo2_max || '-'} unit="ml/kg/min" status="good" />
            <KpiCard title="BMI" value={profile.bmi || '-'} status="good" />
            <KpiCard title="体重" value={profile.weight_kg || '-'} unit="kg" status="good" />
            <KpiCard title="年龄" value={profile.age || '-'} unit="岁" status="good" />
          </div>
        </section>

        {/* Training KPIs */}
        <section style={{ marginBottom: '24px' }}>
          <h2 style={{ fontSize: '13px', fontWeight: '500', color: 'var(--text-muted)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>训练状态</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
            <KpiCard title="训练准备度" value={training?.readiness_score || '-'} unit="/100" status="warning" />
            <KpiCard title="ACWR" value={training?.acwr || '-'} status="warning" />
            <KpiCard title="耐力评分" value={training?.endurance_score || '-'} status="good" />
            <KpiCard title="爬坡评分" value={training?.hill_score || '-'} status="good" />
          </div>
        </section>

        {/* Running & Sleep */}
        <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>跑步数据</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>总跑量</div>
                <div style={{ fontSize: '20px', fontWeight: '600', color: 'var(--primary)' }}>{running?.total_km?.toFixed(1) || '-'} <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>km</span></div>
              </div>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>跑步次数</div>
                <div style={{ fontSize: '20px', fontWeight: '600', color: 'var(--secondary)' }}>{running?.total_runs || '-'}</div>
              </div>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>平均配速</div>
                <div style={{ fontSize: '20px', fontWeight: '600', color: 'var(--accent)' }}>{running?.avg_pace_min_per_km || '-'}<span style={{ fontSize: '12px', color: 'var(--text-muted)' }}> min/km</span></div>
              </div>
            </div>
          </div>

          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>睡眠数据</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>平均时长</div>
                <div style={{ fontSize: '20px', fontWeight: '600', color: 'var(--primary)' }}>{sleep?.avg_total_hours || '-'}<span style={{ fontSize: '12px', color: 'var(--text-muted)' }}> h</span></div>
              </div>
              <div style={{ padding: '12px', background: 'var(--surface-elevated)', borderRadius: '6px' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>深睡占比</div>
                <div style={{ fontSize: '20px', fontWeight: '600', color: 'var(--secondary)' }}>{sleep?.deep_pct || '-'}%</div>
              </div>
            </div>
          </div>
        </section>

        {/* Charts */}
        <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>本周跑量</h3>
            <LineChart data={weeklyData} height={200} color="var(--primary)" />
          </div>
          <div className="card">
            <h3 style={{ fontSize: '14px', fontWeight: '500', color: 'var(--text-secondary)', marginBottom: '16px' }}>月度趋势</h3>
            <LineChart data={monthlyData} height={200} color="var(--secondary)" />
          </div>
        </section>

        {/* Navigation */}
        <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <a href="/bigscreen" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📊</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>数据大屏</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>全屏展示</div>
            </div>
          </a>
          <a href="/report" className="card" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
            <span style={{ fontSize: '20px' }}>📋</span>
            <div>
              <div style={{ fontSize: '14px', fontWeight: '500', color: 'white' }}>AI 健康报告</div>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>查看详情</div>
            </div>
          </a>
        </section>
      </main>
    </div>
  );
}