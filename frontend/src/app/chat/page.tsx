'use client';

// /chat — AI 对话 (2026-06-25 v2: 直接调 oMLX 算力后台)
// 历史版本:
//   v1 (2026-05-18): 多轮对话 + 文件上传
//   v2 (2026-06-24): 接入 Button/useToast 错误处理
//   v3 (2026-06-25): 改用 /api/v1/llm/chat 直接调 oMLX 算力后台,不走 Swarm 工作流

import { useEffect, useRef, useState } from 'react';
import { Header } from '@/components/layout/header';
import { Button, useToast } from '@/components/ui';
import { api, getAuthToken } from '@/lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  model?: string;
  latency_ms?: number;
}

const MAX_HISTORY = 10;  // 后端上限 10 轮

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [lastModel, setLastModel] = useState<string>('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

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
      // 文件上传(保留旧功能,走 /upload/file 端点)
      if (files.length > 0) {
        for (const file of files) {
          const formData = new FormData();
          formData.append('file', file);
          const res = await fetch('/qm/api/upload/file', {
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

      // 文本对话 → 直接调 oMLX
      if (text) {
        // 构造 history:最近 MAX_HISTORY 轮(不含当前 message)
        const history = messages
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .slice(-MAX_HISTORY * 2)  // user+assistant 各 1 算 1 轮
          .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));

        const data = await api.chatWithLLM(text, history, { max_tokens: 1024 });
        const assistantMsg: Message = {
          id: `msg-${Date.now()}-reply`,
          role: 'assistant',
          content: data.reply,
          timestamp: new Date().toISOString(),
          model: data.model,
          latency_ms: data.latency_ms,
        };
        setMessages(prev => [...prev, assistantMsg]);
        setLastModel(data.model);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '请求失败';
      const errMsg: Message = {
        id: `msg-err-${Date.now()}`,
        role: 'assistant',
        content: `❌ ${msg}`,
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, errMsg]);
      toast.error(msg);
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

  const clearHistory = () => {
    setMessages([]);
    setLastModel('');
  };

  const formatTime = (ts: string) => {
    if (!ts) return '';
    return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  // 解析模型简称
  const modelShort = (m?: string) => {
    if (!m) return '';
    return m.replace(/^omlX:\/\//, '').replace(/-it-\d+bit$/, '');
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--background)]">
      <Header title="Chat 助手" activePath="/chat" />

      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col px-6">
        {/* 算力后台指示器 */}
        <div className="flex items-center justify-between border-b border-[var(--border)] py-2 text-[11px] text-[var(--text-muted)]">
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--primary)]" />
            <span>算力后台: <span className="font-mono text-[var(--text-secondary)]">
              {lastModel ? modelShort(lastModel) : 'omlX gemma-4-12B'}
            </span></span>
          </div>
          {messages.length > 0 && (
            <button
              onClick={clearHistory}
              className="cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-white"
            >
              清空对话
            </button>
          )}
        </div>

        {/* 消息区 */}
        <div className="flex-1 overflow-y-auto py-6">
          {messages.length === 0 && (
            <div className="px-5 py-20 text-center">
              <div className="mb-4 text-[48px]">💬</div>
              <h2 className="mb-2 text-lg font-medium text-white">RHYTHMIND 健康助手</h2>
              <p className="mx-auto max-w-[400px] text-sm leading-relaxed text-[var(--text-muted)]">
                基于 oMLX 本地算力后台的多轮对话，可咨询训练、睡眠、营养、健康数据等问题
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {['我的训练准备度如何？', '如何提高 VO2 Max？', '最近睡眠质量分析', '推荐一次恢复跑'].map(q => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); }}
                    className="cursor-pointer rounded-full border border-[var(--border)] text-xs px-3.5 py-2 bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:border-[var(--primary)]"
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
                  className={`max-w-[70%] rounded-xl px-3.5 py-2.5 ${
                    isUser
                      ? 'bg-[var(--primary)] text-white'
                      : 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-secondary)]'
                  }`}
                >
                  <div className="whitespace-pre-wrap text-[13px] leading-relaxed break-words">
                    {msg.content}
                  </div>
                  <div className={`mt-1.5 flex items-center gap-2 text-[10px] ${
                    isUser ? 'text-white/60 justify-end' : 'text-[var(--text-muted)]'
                  }`}>
                    <span>{formatTime(msg.timestamp)}</span>
                    {!isUser && msg.latency_ms !== undefined && (
                      <span className="font-mono">· {(msg.latency_ms / 1000).toFixed(1)}s</span>
                    )}
                    {!isUser && msg.model && (
                      <span className="font-mono opacity-70">{modelShort(msg.model)}</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {loading && (
            <div className="mb-3 flex">
              <div className="rounded-xl px-3.5 py-2.5 text-[13px] bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)]">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]" />
                  算力后台思考中…
                </span>
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
                className="flex items-center gap-1.5 rounded-md border border-[var(--border)] text-xs px-2.5 py-1 bg-[var(--surface)] text-[var(--text-secondary)]"
              >
                <span>{getFileIcon(f.name)}</span>
                <span className="max-w-[120px] truncate">{f.name}</span>
                <button
                  onClick={() => removeFile(i)}
                  className="cursor-pointer border-none px-0.5 bg-transparent text-[var(--text-muted)]"
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
              className="shrink-0 cursor-pointer rounded-lg border border-[var(--border)] text-base p-2.5 bg-[var(--surface)] text-[var(--text-secondary)] transition-colors hover:border-[var(--primary)]"
              title="上传文件"
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
              placeholder="向健康助手提问…"
              rows={1}
              className="min-h-10 max-h-[120px] flex-1 resize-none rounded-lg border border-[var(--border)] text-sm leading-relaxed text-white outline-none px-3.5 py-2.5 bg-[var(--surface)] transition-colors focus:border-[var(--primary)]"
            />
            <Button
              variant="primary"
              size="md"
              onClick={sendMessage}
              disabled={loading || (!input.trim() && files.length === 0)}
              loading={loading}
            >
              发送
            </Button>
          </div>
          <p className="mt-2 text-[10px] text-[var(--text-muted)]">
            算力后台: omlX gemma-4-12B-it-4bit (本地推理) · Enter 发送，Shift+Enter 换行
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
