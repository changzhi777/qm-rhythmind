'use client';

import { useEffect, useRef, useState } from 'react';
import { Header } from '@/components/layout/header';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

function getAuthToken(): string {
  if (typeof window === 'undefined') return 'garmin_user_001';
  return localStorage.getItem('auth_token') || 'garmin_user_001';
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

      // 发送文本对话
      if (text) {
        const res = await fetch('/qm/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${getAuthToken()}`,
          },
          body: JSON.stringify({ text, context: {} }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const reply = data?.data?.coach_response || data?.message || JSON.stringify(data?.data || data);
        const assistantMsg: Message = {
          id: `msg-${Date.now()}-reply`,
          role: 'assistant',
          content: typeof reply === 'string' ? reply : JSON.stringify(reply, null, 2),
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
    <div style={{ minHeight: '100vh', background: 'var(--background)', display: 'flex', flexDirection: 'column' }}>
      <Header title="Chat 助手" activePath="/chat" />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', maxWidth: '900px', width: '100%', margin: '0 auto', padding: '0 24px' }}>
        {/* 消息区 */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px 0' }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', padding: '80px 20px' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>💬</div>
              <h2 style={{ fontSize: '18px', color: 'white', fontWeight: '500', marginBottom: '8px' }}>RHYTHMIND 健康助手</h2>
              <p style={{ fontSize: '14px', color: 'var(--text-muted)', maxWidth: '400px', margin: '0 auto', lineHeight: '1.6' }}>
                可以向我提问健康问题、上传数据文件、医学报告或图像进行分析
              </p>
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'center', marginTop: '24px', flexWrap: 'wrap' }}>
                {['我的训练准备度如何？', '分析一下我的睡眠数据', '最近的跑步表现怎么样？'].map(q => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); }}
                    style={{
                      padding: '8px 14px', background: 'var(--surface)', border: '1px solid var(--border)',
                      borderRadius: '20px', color: 'var(--text-secondary)', fontSize: '12px', cursor: 'pointer',
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} style={{
              display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
              marginBottom: '12px',
            }}>
              <div style={{
                maxWidth: '70%', padding: '10px 14px', borderRadius: '12px',
                background: msg.role === 'user' ? 'var(--primary)' : 'var(--surface)',
                border: msg.role === 'assistant' ? '1px solid var(--border)' : 'none',
              }}>
                <div style={{
                  fontSize: '13px', color: msg.role === 'user' ? 'white' : 'var(--text-secondary)',
                  lineHeight: '1.6', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}>
                  {msg.content}
                </div>
                <div style={{ fontSize: '10px', color: msg.role === 'user' ? 'rgba(255,255,255,0.6)' : 'var(--text-muted)', marginTop: '4px', textAlign: 'right' }}>
                  {formatTime(msg.timestamp)}
                </div>
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: 'flex', marginBottom: '12px' }}>
              <div style={{ padding: '10px 14px', borderRadius: '12px', background: 'var(--surface)', border: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>思考中...</span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 文件预览 */}
        {files.length > 0 && (
          <div style={{ display: 'flex', gap: '8px', padding: '8px 0', flexWrap: 'wrap' }}>
            {files.map((f, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '4px 10px', background: 'var(--surface)', borderRadius: '6px',
                border: '1px solid var(--border)', fontSize: '12px', color: 'var(--text-secondary)',
              }}>
                <span>{getFileIcon(f.name)}</span>
                <span style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                <button onClick={() => removeFile(i)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '0 2px' }}>×</button>
              </div>
            ))}
          </div>
        )}

        {/* 输入区 */}
        <div style={{ padding: '16px 0', borderTop: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
            <button
              onClick={() => fileInputRef.current?.click()}
              style={{
                padding: '10px', background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: '8px', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '16px',
                flexShrink: 0,
              }}
            >
              ＋
            </button>
            <input ref={fileInputRef} type="file" multiple onChange={handleFileChange} style={{ display: 'none' }} accept=".csv,.json,.pdf,.png,.jpg,.jpeg,.txt,.xml" />
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息或上传文件..."
              rows={1}
              style={{
                flex: 1, padding: '10px 14px', background: 'var(--surface)',
                border: '1px solid var(--border)', borderRadius: '8px',
                color: 'white', fontSize: '14px', resize: 'none', outline: 'none',
                minHeight: '40px', maxHeight: '120px', lineHeight: '1.5',
              }}
            />
            <button
              onClick={sendMessage}
              disabled={loading || (!input.trim() && files.length === 0)}
              style={{
                padding: '10px 16px', background: 'var(--primary)', border: 'none',
                borderRadius: '8px', color: 'white', fontSize: '14px', fontWeight: '500',
                cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.5 : 1,
                flexShrink: 0,
              }}
            >
              发送
            </button>
          </div>
          <p style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '8px' }}>
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
