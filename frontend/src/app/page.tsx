'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, setAuthToken, type UserSummary } from '@/lib/api';

export default function HomePage() {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    return () => clearTimeout(t);
  }, []);

  async function loadUsers() {
    setLoading(true);
    try {
      const res = await api.getUsersSummary();
      setUsers(res.users || []);
    } catch {
      console.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!mounted) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- pre-existing data fetch pattern
    loadUsers();
  }, [mounted]);

  function selectUser(userId: string) {
    setAuthToken(userId);
    const u = users.find(u => u.user_id === userId);
    if (u && typeof window !== 'undefined') {
      localStorage.setItem('user_display', JSON.stringify({ avatar: u.avatar, name: u.display_name }));
    }
    router.push('/dashboard');
  }

  if (!mounted) return null;

  return (
    <div className="min-h-screen bg-[var(--background)] text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--border)] px-6 py-4">
        <div className="max-w-[900px] mx-auto flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center"
            style={{ background: 'var(--primary)' }}
          >
            <span className="text-white font-bold text-lg">R</span>
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold text-white">RHYTHMIND</span>
              <span className="text-sm font-medium" style={{ color: 'var(--primary)' }}>律动</span>
              <span className="text-xs text-gray-500">v0.2.0</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">多智能体 AI 健康管理平台</p>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 flex flex-col items-center justify-center px-4 py-12">
        <h1 className="text-2xl font-bold mb-2">选择用户</h1>
        <p className="text-gray-400 text-sm mb-8">选择一个用户以查看其健康数据</p>

        {loading ? (
          <div className="text-gray-400 py-8">加载中...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-[900px] w-full">
            {users.map((u) => (
              <UserCard key={u.user_id} user={u} onSelect={() => selectUser(u.user_id)} />
            ))}
          </div>
        )}

        {users.length === 0 && !loading && (
          <div className="text-gray-500 py-12">暂无用户数据</div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-[var(--border)] px-6 py-3 text-center">
        <p className="text-xs text-gray-600">
          湖南青沐生命科技有限公司 · RHYTHMIND 律动
        </p>
      </footer>
    </div>
  );
}

function UserCard({ user, onSelect }: { user: UserSummary; onSelect: () => void }) {
  const totalRuns = user.running?.total_runs || 0;
  const totalKm = user.running?.total_km || 0;
  const avgPace = user.running?.avg_pace_min_per_km;

  return (
    <button
      onClick={onSelect}
      className="bg-[var(--surface)] rounded-xl p-6 text-left hover:bg-[var(--surface-elevated)] transition-colors border border-transparent hover:border-[var(--primary)]/30 w-full"
    >
      {/* 用户信息 */}
      <div className="flex items-center gap-4 mb-4">
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center text-lg font-bold"
          style={{ background: 'var(--primary)', color: '#111' }}
        >
          {user.avatar}
        </div>
        <div className="flex-1">
          <div className="text-lg font-semibold text-white">{user.display_name}</div>
          <div className="text-xs text-gray-500">
            {user.user_id}
            {user.profile.gender && ` · ${user.profile.gender === 'MALE' ? '男' : '女'}`}
            {user.profile.age && ` · ${user.profile.age}岁`}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-gray-500">{user.facts_count} 条数据</div>
          {user.has_medical && (
            <span className="text-xs px-2 py-0.5 rounded bg-green-400/10 text-green-400">
              含医疗记录
            </span>
          )}
        </div>
      </div>

      {/* KPI 概览 */}
      <div className="grid grid-cols-3 gap-3">
        <KpiItem label="跑步次数" value={totalRuns > 0 ? `${totalRuns} 次` : '-'} />
        <KpiItem label="总跑量" value={totalKm > 0 ? `${totalKm.toFixed(0)} km` : '-'} />
        <KpiItem
          label="平均配速"
          value={avgPace ? `${Math.floor(avgPace)}'${String(Math.round((avgPace % 1) * 60)).padStart(2, '0')}"` : '-'}
        />
      </div>

      {/* 第二行 KPI */}
      {(user.profile.vo2_max || (user.active_medications ?? 0) > 0 || (user.abnormal_labs ?? 0) > 0) && (
        <div className="grid grid-cols-3 gap-3 mt-3">
          <KpiItem label="VO2 Max" value={user.profile.vo2_max ? String(user.profile.vo2_max) : '-'} />
          <KpiItem label="当前用药" value={`${user.active_medications ?? 0} 种`} />
          <KpiItem
            label="异常指标"
            value={(user.abnormal_labs ?? 0) > 0 ? `${user.abnormal_labs} 项` : '正常'}
            highlight={(user.abnormal_labs ?? 0) > 0}
          />
        </div>
      )}
    </button>
  );
}

function KpiItem({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-[var(--background)] rounded-lg p-2.5">
      <div className="text-[10px] text-gray-500 mb-0.5">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? 'text-red-400' : 'text-white'}`}>
        {value}
      </div>
    </div>
  );
}
