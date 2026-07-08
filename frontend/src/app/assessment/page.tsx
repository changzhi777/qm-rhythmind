'use client';

// /assessment — 跨领域智能评估 (康复 + 营养 + 运动)
// 2026-07-07 新增: 基于 3 本国家职业技能标准
// 三段式: start() → question() × N → complete() → 3 维评分 + 综合建议

import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Header } from '@/components/layout/header';
import { Button, ErrorState, useToast } from '@/components/ui';
import { useAssessmentStore } from '@/lib/stores/assessment-store';

const DIM_COLORS = {
  rehab: { label: '康复', color: 'text-cyan-400', bg: 'bg-cyan-500/10' },
  nutrition: { label: '营养', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  training: { label: '运动', color: 'text-green-400', bg: 'bg-green-500/10' },
} as const;

export default function AssessmentPage() {
  const {
    sessionId,
    currentState,
    missingDimensions,
    currentQuestion,
    answers,
    loading,
    error,
    result,
    resultError,
    start,
    answer,
    complete,
    reset,
  } = useAssessmentStore();
  const toast = useToast();
  const [selected, setSelected] = useState<string>('');

  // 启动评估
  useEffect(() => {
    if (!sessionId && !result) {
      start().catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 启动/重置时清空选择
  useEffect(() => {
    setSelected('');
  }, [currentQuestion?.question]);

  // 自动重试 + 错误处理
  if (error && !sessionId) {
    return (
      <div className="min-h-screen bg-[var(--background)]">
        <Header title="跨领域评估" activePath="/assessment" />
        <main className="mx-auto max-w-[800px] p-6">
          <ErrorState
            error={error}
            onRetry={() => start().catch(() => undefined)}
          />
        </main>
      </div>
    );
  }

  // 结果页
  if (result) {
    return (
      <div className="min-h-screen bg-[var(--background)]">
        <Header title="评估结果" activePath="/assessment" />
        <main className="mx-auto max-w-[1000px] p-6">
          {/* 3 维评分卡片 */}
          <div className="mb-6 grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
            {(['rehab', 'nutrition', 'training'] as const).map(dim => {
              const score = result.scores[dim];
              const color =
                score >= 80 ? 'text-green-400' :
                score >= 60 ? 'text-blue-400' :
                score >= 40 ? 'text-amber-400' : 'text-red-400';
              const level =
                score >= 80 ? '优秀' :
                score >= 60 ? '良好' :
                score >= 40 ? '一般' : '需改善';
              return (
                <div
                  key={dim}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5"
                >
                  <div className="mb-2 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
                    {DIM_COLORS[dim].label}维度
                  </div>
                  <div className={`text-4xl font-bold ${color}`}>{score}</div>
                  <div className={`mt-1 text-sm ${color}`}>{level}</div>
                </div>
              );
            })}
          </div>

          {/* 综合建议 */}
          <div className="card mb-4">
            <h2 className="mb-3 text-base font-semibold text-white">综合建议</h2>
            <div className="markdown-body text-sm leading-relaxed text-[var(--text-secondary)]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {result.advice}
              </ReactMarkdown>
            </div>
          </div>

          <div className="flex gap-2">
            <Button variant="primary" onClick={() => { reset(); start().catch(() => undefined); }}>
              重新评估
            </Button>
            <a href="/dashboard">
              <Button>查看大屏</Button>
            </a>
          </div>
        </main>
      </div>
    );
  }

  // 评估进行中
  return (
    <div className="min-h-screen bg-[var(--background)]">
      <Header title="跨领域评估" activePath="/assessment" />
      <main className="mx-auto max-w-[700px] p-6">
        {/* 顶部状态 */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="mb-1 text-xl font-semibold text-white">智能健康评估</h1>
            <p className="text-xs text-[var(--text-muted)]">
              基于《康复治疗师》《公共营养师》《社会体育指导员》三本国家职业技能标准
            </p>
          </div>
          <div className="text-right">
            <div className="text-[11px] text-[var(--text-muted)]">已回答</div>
            <div className="text-2xl font-bold text-[var(--primary)]">
              {answers.length}
            </div>
          </div>
        </div>

        {/* 维度进度 */}
        <div className="mb-6 flex gap-2">
          {(['rehab', 'nutrition', 'training'] as const).map(dim => {
            const isCurrent = currentQuestion?.dimension === dim;
            const answered = answers.some(a => a.dimension === dim);
            return (
              <div
                key={dim}
                className={`flex-1 rounded-md px-3 py-2 text-center text-xs ${
                  isCurrent
                    ? 'border-2 border-[var(--primary)] bg-[var(--primary)]/10 text-white'
                    : answered
                    ? 'border border-green-500/30 bg-green-500/10 text-green-300'
                    : 'border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)]'
                }`}
              >
                {DIM_COLORS[dim].label}
                {answered && !isCurrent && ' ✓'}
              </div>
            );
          })}
        </div>

        {/* 加载中 */}
        {loading && !currentQuestion && (
          <div className="card text-center">
            <div className="text-sm text-[var(--text-muted)]">正在启动评估...</div>
          </div>
        )}

        {/* 当前问题 */}
        {currentQuestion && (
          <div className="card">
            <div className="mb-2 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              {DIM_COLORS[currentQuestion.dimension as keyof typeof DIM_COLORS]?.label || currentQuestion.dimension} 评估
            </div>
            <div className="mb-5 text-base font-medium text-white">
              {currentQuestion.question}
            </div>

            {/* 选项(选择题) */}
            {currentQuestion.options.length > 0 ? (
              <div className="mb-5 space-y-2">
                {currentQuestion.options.map((opt, i) => (
                  <button
                    key={i}
                    onClick={() => setSelected(opt)}
                    className={`w-full cursor-pointer rounded-md border px-4 py-3 text-left text-sm transition-colors ${
                      selected === opt
                        ? 'border-[var(--primary)] bg-[var(--primary)]/10 text-white'
                        : 'border-[var(--border)] bg-[var(--surface)] text-[var(--text-secondary)] hover:border-[var(--primary)]/50'
                    }`}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            ) : (
              /* 自由文本输入(无选项) */
              <textarea
                value={selected}
                onChange={e => setSelected(e.target.value)}
                placeholder="请输入您的回答..."
                rows={3}
                className="mb-5 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-white outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--primary)]"
              />
            )}

            <div className="flex justify-end gap-2">
              {currentQuestion.is_final ? (
                <Button
                  variant="primary"
                  onClick={() => complete().catch(() => undefined)}
                  loading={loading}
                >
                  生成综合建议
                </Button>
              ) : (
                <Button
                  variant="primary"
                  onClick={() => answer(selected).catch(() => undefined)}
                  loading={loading}
                  disabled={!selected.trim()}
                >
                  下一题 →
                </Button>
              )}
            </div>
          </div>
        )}

        {/* 错误 */}
        {error && (
          <div className="mt-4">
            <ErrorState error={error} onRetry={() => start().catch(() => undefined)} />
          </div>
        )}

        {/* 已用数据 */}
        {Object.keys(currentState).length > 0 && answers.length === 0 && (
          <details className="mt-4 rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--text-muted)]">
            <summary className="cursor-pointer">已用健康数据 ({Object.keys(currentState).length} 项)</summary>
            <pre className="mt-2 max-h-40 overflow-auto text-[10px]">
              {JSON.stringify(currentState, null, 2)}
            </pre>
          </details>
        )}
      </main>
    </div>
  );
}
