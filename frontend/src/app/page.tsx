'use client';

// / — 用户选择首页(Stage 3 + v3 首页改造:上下排列大卡)
// 2026-06-24 frontend-polish Stage 3 + 27 + 38

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api, setAuthToken, type UserSummary, type Persona } from '@/lib/api';
import {
  Card,
  EmptyState,
  ErrorState,
  SkeletonGroup,
  useToast,
} from '@/components/ui';

interface UserWithPersona extends UserSummary {
  persona?: Persona | null;
}

export default function HomePage() {
  const [users, setUsers] = useState<UserWithPersona[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    return () => clearTimeout(t);
  }, []);

  async function loadUsers() {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getUsersSummary();
      const list = res.users || [];
      const withPersona = await Promise.all(
        list.map(async (u) => {
          try {
            const p = await api.getUserPersona(u.user_id);
            return { ...u, persona: p.persona } as UserWithPersona;
          } catch {
            return { ...u, persona: null } as UserWithPersona;
          }
        }),
      );
      setUsers(withPersona);
    } catch (e) {
      const msg = e instanceof Error ? e.message : '加载失败';
      setError(msg);
      toast.error(`用户列表加载失败: ${msg}`);
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
    const u = users.find((x) => x.user_id === userId);
    if (u && typeof window !== 'undefined') {
      localStorage.setItem('user_display', JSON.stringify({ avatar: u.avatar, name: u.display_name }));
    }
    if (u) toast.success(`已选择用户 ${u.display_name}`);
    // v3: 跳转到数据大屏(深度展示)
    router.push('/bigscreen');
  }

  if (!mounted) return null;

  return (
    <div className="min-h-screen bg-[var(--background)] text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--border)] px-6 py-4">
        <div className="max-w-[900px] mx-auto flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center bg-[var(--primary)]">
            <span className="text-white font-bold text-lg">R</span>
          </div>
          <div>
            <div className="flex items-baseline gap-2">
              <span className="text-xl font-bold text-white">RHYTHMIND</span>
              <span className="text-sm font-medium text-[var(--primary)]">律动</span>
              <span className="text-xs text-gray-500">v0.2.0</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">多智能体 AI 健康管理平台</p>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 flex flex-col items-center px-4 py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold mb-2">选择用户</h1>
          <p className="text-gray-400 text-sm">选择一个用户以查看其健康数据大屏</p>
        </div>

        {error && !loading ? (
          <ErrorState error={error} onRetry={loadUsers} />
        ) : loading ? (
          <div className="w-full max-w-[800px]">
            <SkeletonGroup count={2} height={220} />
          </div>
        ) : users.length === 0 ? (
          <Card>
            <EmptyState
              icon="👥"
              title="暂无用户数据"
              description="请先在系统中创建用户"
            />
          </Card>
        ) : (
          // v3: 上下垂直排列(单列)
          <div className="flex flex-col gap-6 w-full max-w-[800px]">
            {users.map((u) => (
              <UserCard key={u.user_id} user={u} onSelect={() => selectUser(u.user_id)} />
            ))}
          </div>
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

function UserCard({
  user,
  onSelect,
}: {
  user: UserWithPersona;
  onSelect: () => void;
}) {
  const totalRuns = user.running?.total_runs || 0;
  const totalKm = user.running?.total_km || 0;
  const avgPace = user.running?.avg_pace_min_per_km;
  const persona = user.persona;

  return (
    // v3: 大卡 + 手提箱效果(hover 提升 + 阴影 + 边框变色)
    <button
      type="button"
      onClick={onSelect}
      className="
        group relative w-full text-left
        bg-[var(--surface)] rounded-2xl p-8
        border-2 border-transparent
        hover:border-[var(--primary)]/60
        hover:bg-[var(--surface-elevated)]
        hover:shadow-2xl hover:shadow-[var(--primary)]/10
        hover:-translate-y-1
        transition-all duration-300 ease-[var(--ease-out-soft)]
        cursor-pointer
      "
    >
      {/* 顶部:大头像 + 用户信息 + 切换大屏按钮 */}
      <div className="flex items-start gap-6 mb-6">
        {/* v3: 渐变大头像 + hover 微缩放 */}
        <div
          className="
            shrink-0 w-20 h-20 rounded-2xl
            flex items-center justify-center
            text-2xl font-bold text-[#111]
            bg-gradient-to-br from-[var(--primary)] to-[var(--secondary)]
            shadow-lg shadow-[var(--primary)]/20
            group-hover:scale-105 group-hover:shadow-[var(--primary)]/40
            transition-all duration-300
          "
          aria-hidden="true"
        >
          {user.avatar}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1 flex-wrap">
            <h2 className="text-2xl font-bold text-white">{user.display_name}</h2>
            <span className="text-sm text-[var(--text-muted)] font-mono">
              {user.user_id}
            </span>
            {user.has_medical && (
              <span className="text-xs px-2 py-0.5 rounded bg-green-400/10 text-green-400 border border-green-400/30">
                含医疗
              </span>
            )}
          </div>
          <div className="text-sm text-[var(--text-secondary)] flex items-center gap-2 flex-wrap">
            {user.profile.gender && <span>{user.profile.gender === 'MALE' ? '男' : '女'}</span>}
            {user.profile.age && <span>· {user.profile.age}岁</span>}
            {user.facts_count > 0 && <span>· {user.facts_count} 条数据</span>}
          </div>
        </div>

        {/* v3: "切换大屏"独立按钮(阻止冒泡) */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelect();
          }}
          className="
            shrink-0 px-4 py-2 rounded-lg
            bg-[var(--primary)]/15 text-[var(--primary)]
            border border-[var(--primary)]/30
            hover:bg-[var(--primary)] hover:text-white
            transition-all duration-200
            text-sm font-medium
            flex items-center gap-1.5
            opacity-60 group-hover:opacity-100
          "
          aria-label={`切换到 ${user.display_name} 的数据大屏`}
        >
          📊 切换大屏
        </button>
      </div>

      {/* v3: 重点突出 PERSONA 区块(渐变背景 + 主色边框) */}
      {persona ? (
        <div
          className="
            mb-5 p-5 rounded-xl
            bg-gradient-to-br from-[var(--primary)]/8 to-[var(--secondary)]/8
            border border-[var(--primary)]/30
            relative overflow-hidden
          "
        >
          {/* 装饰角标 */}
          <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-bl from-[var(--primary)]/15 to-transparent rounded-bl-full" />

          <div className="relative">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs uppercase tracking-wider text-[var(--primary)]/80 font-semibold">
                人物画像
              </span>
            </div>
            <h3 className="text-lg font-bold text-[var(--primary)] mb-2">
              {persona.title}
            </h3>
            <p className="text-[15px] text-white leading-relaxed mb-3">
              {persona.summary}
            </p>
            {persona.background && (
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed italic mb-3">
                {persona.background}
              </p>
            )}
            {(persona.strengths?.length || persona.concerns?.length) ? (
              <div className="flex flex-wrap gap-2">
                {persona.strengths?.map((s, i) => (
                  <span
                    key={`s${i}`}
                    className="text-xs px-2.5 py-1 rounded-md
                               bg-[var(--status-good)]/15 text-[var(--status-good)]
                               border border-[var(--status-good)]/30
                               flex items-center gap-1"
                  >
                    ✓ {s}
                  </span>
                ))}
                {persona.concerns?.map((c, i) => (
                  <span
                    key={`c${i}`}
                    className="text-xs px-2.5 py-1 rounded-md
                               bg-[var(--status-concerned)]/15 text-[var(--status-concerned)]
                               border border-[var(--status-concerned)]/30
                               flex items-center gap-1"
                  >
                    ⚠ {c}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* v3: 弱化的辅助指标(单行小字,不再抢眼) */}
      <div className="flex items-center gap-3 text-xs text-[var(--text-muted)] flex-wrap">
        <span className="flex items-center gap-1">
          <span className="text-[var(--text-secondary)]">跑步</span>
          <span className="text-white font-medium">{totalRuns}</span>
          <span>次</span>
        </span>
        <span>·</span>
        <span className="flex items-center gap-1">
          <span className="text-[var(--text-secondary)]">总跑量</span>
          <span className="text-white font-medium">{totalKm > 0 ? totalKm.toFixed(0) : '-'}</span>
          <span>km</span>
        </span>
        <span>·</span>
        <span className="flex items-center gap-1">
          <span className="text-[var(--text-secondary)]">配速</span>
          <span className="text-white font-medium">
            {avgPace ? `${Math.floor(avgPace)}'${String(Math.round((avgPace % 1) * 60)).padStart(2, '0')}"` : '-'}
          </span>
        </span>
        <span>·</span>
        <span className="flex items-center gap-1">
          <span className="text-[var(--text-secondary)]">VO2 Max</span>
          <span className="text-white font-medium">{user.profile.vo2_max ?? '-'}</span>
        </span>
        <span className="ml-auto text-[var(--primary)] group-hover:translate-x-1 transition-transform">
          点击进入数据大屏 →
        </span>
      </div>
    </button>
  );
}