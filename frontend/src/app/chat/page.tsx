'use client';

import { useEffect, useRef, useState } from 'react';
import { Header } from '@/components/layout/header';
import { API_BASE, getAuthToken } from '@/lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text && files.length === 0) return;

    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: 'user',
      content: text || `上传了 ${files.length} 个文件`,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setFiles([]);
    setLoading(true);

    try {
      // 如果有文件，先上传
      if (files.length > 0) {
        for (const file of files) {
          const formData = new FormData();
          formData.append('file', file);
          const res = await fetch(`${API_BASE}/upload/file`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${getAuthToken()}` },
            body: formData,
          });
          if (!res.ok) throw new Error(`上传失败: ${file.name}`);
          const data = await res.json();
          const uploadMsg: Message = {
            id: `msg-upload-${Date.now()}-${file.name}`,
            role: 'assistant',
            content: `✅ 已上传 **${file.name}**\n${data.summary || data.message || '文件已入库'}`,
            timestamp: new Date().toISOString(),
          };
          setMessages(prev => [...prev, uploadMsg]);
        }
      }

      // 发送文本对话
      if (text) {
        const res = await fetch(`${API_BASE}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getAuthToken()}`,
          },
          body: JSON.stringify({ text, context: {} }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.status === 'throttled') {
          const throttledMsg: Message = {
            id: `msg-${Date.now()}-reply`,
            role: 'assistant',
            content: `⏳ ${data.message || '操作过于频繁，请稍后再试。'}`,
            timestamp: new Date().toISOString(),
          };
          setMessages(prev => [...prev, throttledMsg]);
          return;
        }
        const reply = formatChatReply(data);
        const assistantMsg: Message = {
          id: `msg-${Date.now()}-reply`,
          role: 'assistant',
          content: reply,
          timestamp: new Date().toISOString(),
        };
        setMessages(prev => [...prev, assistantMsg]);
      }
    } catch (err) {
      const errMsg: Message = {
        id: `msg-err-${Date.now()}`,
        role: 'assistant',
        content: `❌ ${err instanceof Error ? err.message : '请求失败'}`,
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(prev => [...prev, ...Array.from(e.target.files!)]);
    }
    e.target.value = '';
  };

  const removeFile = (idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const formatTime = (ts: string) => {
    if (!ts) return '';
    return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--background)]">
      <Header title="Chat 助手" activePath="/chat" />

      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col px-6">
        {/* 消息区 */}
        <div className="flex-1 overflow-y-auto py-6">
          {messages.length === 0 && (
            <div className="px-5 py-20 text-center">
              <div className="mb-4 text-[48px]">💬</div>
              <h2 className="mb-2 text-lg font-medium text-white">RHYTHMIND 健康助手</h2>
              <p className="mx-auto max-w-[400px] text-sm leading-relaxed text-[var(--text-muted)]">
                可以向我提问健康问题、上传数据文件、医学报告或图像进行分析
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {['我的训练准备度如何？', '分析一下我的睡眠数据', '最近的跑步表现怎么样？'].map(q => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); }}
                    className="cursor-pointer rounded-full border border-[var(--border)] text-xs"
                    style={{
                      padding: '8px 14px',
                      background: 'var(--surface)',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                className={`mb-3 flex ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className="max-w-[70%] rounded-xl p-2.5"
                  style={{
                    padding: '10px 14px',
                    background: isUser ? 'var(--primary)' : 'var(--surface)',
                    border: isUser ? 'none' : '1px solid var(--border)',
                  }}
                >
                  <div
                    className="whitespace-pre-wrap text-[13px] leading-relaxed break-words"
                    style={{
                      color: isUser ? 'white' : 'var(--text-secondary)',
                    }}
                  >
                    {msg.content}
                  </div>
                  <div
                    className="mt-1 text-right text-[10px]"
                    style={{
                      color: isUser ? 'rgba(255,255,255,0.6)' : 'var(--text-muted)',
                    }}
                  >
                    {formatTime(msg.timestamp)}
                  </div>
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="mb-3 flex">
              <div
                className="rounded-xl text-[13px]"
                style={{
                  padding: '10px 14px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                }}
              >
                思考中...
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 文件预览 */}
        {files.length > 0 && (
          <div className="flex flex-wrap gap-2 py-2">
            {files.map((f, i) => (
              <div
                key={i}
                className="flex items-center gap-1.5 rounded-md border border-[var(--border)] text-xs"
                style={{
                  padding: '4px 10px',
                  background: 'var(--surface)',
                  color: 'var(--text-secondary)',
                }}
              >
                <span>{getFileIcon(f.name)}</span>
                <span className="max-w-[120px] truncate">{f.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="cursor-pointer border-none px-0.5"
                  style={{ background: 'none', color: 'var(--text-muted)' }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {/* 输入区 */}
        <div className="border-t border-[var(--border)] py-4">
          <div className="flex items-end gap-2">
            <button
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 cursor-pointer rounded-lg border border-[var(--border)] text-base"
              style={{
                padding: '10px',
                background: 'var(--surface)',
                color: 'var(--text-secondary)',
              }}
            >
              ＋
            </button>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileChange}
              className="hidden"
              accept=".csv,.json,.pdf,.png,.jpg,.jpeg,.txt,.xml"
            />
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息或上传文件..."
              rows={1}
              className="min-h-10 max-h-[120px] flex-1 resize-none rounded-lg border border-[var(--border)] text-sm leading-relaxed text-white outline-none"
              style={{
                padding: '10px 14px',
                background: 'var(--surface)',
              }}
            />
            <button
              onClick={sendMessage}
              disabled={loading || (!input.trim() && files.length === 0)}
              className="shrink-0 cursor-pointer rounded-lg border-none text-sm font-medium text-white"
              style={{
                padding: '10px 16px',
                background: 'var(--primary)',
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.5 : 1,
              }}
            >
              发送
            </button>
          </div>
          <p className="mt-2 text-[10px] text-[var(--text-muted)]">
            支持 CSV、JSON、PDF、图片上传 · Enter 发送，Shift+Enter 换行
          </p>
        </div>
      </main>
    </div>
  );
}

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase();
  const icons: Record<string, string> = { csv: '📊', json: '📋', pdf: '📕', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', txt: '📄', xml: '📄' };
  return icons[ext || ''] || '📎';
}

function formatChatReply(data: Record<string, unknown>): string {
  const d = data?.data as Record<string, unknown> | undefined;
  if (d?.coach_response && typeof d.coach_response === 'string') return d.coach_response;
  if (data?.message && typeof data.message === 'string' && data.message.trim()) return data.message;

  const payload = (d || data) as Record<string, unknown>;
  if (!payload || typeof payload !== 'object') return JSON.stringify(payload);

  const lines: string[] = [];

  const report = payload.data_report as Record<string, unknown> | undefined;
  if (report) {
    if (report.summary) lines.push(`📋 ${report.summary}`);
    const concerns = report.concerns as string[] | undefined;
    if (concerns?.length) lines.push(`⚠️ 关注: ${concerns.join('、')}`);
    if (report.next_suggestion) lines.push(`💡 ${report.next_suggestion}`);
  }

  const plan = payload.training_plan as Record<string, unknown> | undefined;
  if (plan) {
    const today = plan.today_plan as Record<string, unknown> | undefined;
    if (today) {
      lines.push(`\n🏃 今日训练: ${today.name} · ${today.duration_min}分钟 · ${today.intensity}强度`);
      const exercises = today.exercises as string[] | undefined;
      if (exercises?.length) lines.push(`   内容: ${exercises.join(' → ')}`);
    }
    if (plan.recovery_advice) lines.push(`\n🛌 ${plan.recovery_advice}`);
    if (plan.motivation) lines.push(`💪 ${plan.motivation}`);
  }

  if (!lines.length) {
    const summary = typeof report?.summary === 'string' ? report.summary : '';
    return summary || JSON.stringify(payload, null, 2);
  }

  return lines.join('\n');
}
