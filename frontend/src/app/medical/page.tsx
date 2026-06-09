'use client';

import { useEffect, useState } from 'react';
import { Header } from '@/components/layout/header';
import { v } from '@/lib/utils';
import { getAuthToken, V1_BASE } from '@/lib/api';

interface Medication {
  medication_name: string;
  dose: string;
  route: string;
  frequency: string;
  purpose: string;
  start_date: string;
  end_date: string | null;
  status: string;
}

interface LabResult {
  test_name: string;
  test_date: string;
  value: number | null;
  unit: string;
  ref_range: string;
  flag: string | null;
}

interface TimelineEvent {
  event_date: string;
  event_type: string;
  hospital: string;
  department: string;
  duration_days: number | null;
  cost: number | null;
}

interface AnalysisResult {
  status: string;
  summary: string;
  insights: string[];
  concerns: string[];
  recommendations: string[];
  risk_flags: string[];
  confidence: number;
}

type Tab = 'overview' | 'timeline' | 'medications' | 'labs' | 'analysis';

export default function MedicalPage() {
  const [mounted, setMounted] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [medications, setMedications] = useState<Medication[]>([]);
  const [labs, setLabs] = useState<LabResult[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const token = getAuthToken();

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 0);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    loadAllData();
  }, [mounted]);

  async function loadAllData() {
    setLoading(true);
    const headers = { Authorization: `Bearer ${token}` };
    try {
      const [diagRes, tlRes, labsRes] = await Promise.all([
        fetch(`${V1_BASE}/v1/medical/timeline`, { headers }).catch(() => null),
        fetch(`${V1_BASE}/v1/medical/medications`, { headers }).catch(() => null),
        fetch(`${V1_BASE}/v1/medical/labs`, { headers }).catch(() => null),
      ]);

      if (diagRes?.ok) {
        const tlData = await diagRes.json();
        setTimeline(tlData.events || []);
      }
      if (tlRes?.ok) {
        const medData = await tlRes.json();
        setMedications(medData.medications || []);
      }
      if (labsRes?.ok) {
        const labData = await labsRes.json();
        setLabs(labData.results || []);
      }
    } catch (e) {
      console.error('Failed to load medical data:', e);
    } finally {
      setLoading(false);
    }

    fetch(`${V1_BASE}/v1/medical/analyze`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    }).then(r => r.ok ? r.json() : null).then(d => d && setAnalysis(d)).catch(() => {});
  }

  async function triggerAnalysis() {
    setAnalyzing(true);
    try {
      const res = await fetch(`${V1_BASE}/v1/medical/analyze`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });
      if (res.ok) setAnalysis(await res.json());
    } finally {
      setAnalyzing(false);
    }
  }

  if (!mounted) return null;

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: '诊断概览' },
    { key: 'timeline', label: '临床时间线' },
    { key: 'medications', label: '用药记录' },
    { key: 'labs', label: '化验结果' },
    { key: 'analysis', label: 'AI 分析' },
  ];

  const totalCost = timeline.reduce((s, e) => s + (e.cost || 0), 0);
  const activeMeds = medications.filter(m => m.status === 'active').length;
  const abnormalLabs = labs.filter(l => l.flag === 'H' || l.flag === 'L').length;

  return (
    <div className="min-h-screen bg-[var(--background)] text-white">
      <Header title="医疗报告" activePath="/medical" />

      <main className="max-w-[1200px] mx-auto px-4 pb-8">
        {/* KPI 概览 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          <KpiCard label="诊断记录" value={String(timeline.length)} sub="临床事件" />
          <KpiCard label="当前用药" value={String(activeMeds)} sub="种药物" />
          <KpiCard label="化验异常" value={String(abnormalLabs)} sub="项偏高/偏低" />
          <KpiCard label="累计费用" value={totalCost > 0 ? `¥${totalCost.toLocaleString()}` : '-'} sub="医疗支出" />
        </div>

        {/* Tab 切换 */}
        <div className="flex gap-1 mt-6 border-b border-[var(--border)] pb-0">
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                activeTab === tab.key
                  ? 'border-[var(--primary)] text-[var(--primary)]'
                  : 'border-transparent text-gray-400 hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 内容区 */}
        <div className="mt-4">
          {loading ? (
            <div className="text-center py-12 text-gray-400">加载中...</div>
          ) : (
            <>
              {activeTab === 'overview' && <OverviewTab timeline={timeline} medications={medications} labs={labs} />}
              {activeTab === 'timeline' && <TimelineTab events={timeline} />}
              {activeTab === 'medications' && <MedicationsTab medications={medications} />}
              {activeTab === 'labs' && <LabsTab labs={labs} />}
              {activeTab === 'analysis' && (
                <AnalysisTab analysis={analysis} analyzing={analyzing} onAnalyze={triggerAnalysis} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function KpiCard({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-[var(--surface)] rounded-lg p-4">
      <div className="text-xs text-gray-400 mb-1">{label}</div>
      <div className="text-2xl font-bold text-[var(--primary)]">{value}</div>
      <div className="text-xs text-gray-500 mt-1">{sub}</div>
    </div>
  );
}

function OverviewTab({ timeline, medications, labs }: { timeline: TimelineEvent[]; medications: Medication[]; labs: LabResult[] }) {
  const activeMeds = medications.filter(m => m.status === 'active');
  const abnormalLabs = labs.filter(l => l.flag);

  return (
    <div className="space-y-6">
      {/* 最近临床事件 */}
      <section>
        <h3 className="text-lg font-semibold mb-3">最近就医记录</h3>
        <div className="space-y-2">
          {timeline.slice(0, 3).map((e, i) => (
            <div key={i} className="bg-[var(--surface)] rounded-lg p-3 flex justify-between items-center">
              <div>
                <span className="text-[var(--primary)] text-sm">{e.event_date?.slice(0, 10)}</span>
                <span className="ml-2 text-white">{e.event_type}</span>
                {e.department && <span className="ml-2 text-gray-400 text-sm">{e.department}</span>}
              </div>
              {e.cost && <span className="text-gray-400 text-sm">¥{e.cost.toLocaleString()}</span>}
            </div>
          ))}
        </div>
      </section>

      {/* 当前用药 */}
      <section>
        <h3 className="text-lg font-semibold mb-3">当前用药</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {activeMeds.map((m, i) => (
            <div key={i} className="bg-[var(--surface)] rounded-lg p-3">
              <div className="flex justify-between">
                <span className="text-white font-medium">{m.medication_name}</span>
                <span className="text-xs text-green-400 bg-green-400/10 px-2 py-0.5 rounded">{m.status}</span>
              </div>
              <div className="text-sm text-gray-400 mt-1">
                {m.dose} · {m.route} · {m.frequency}
              </div>
              {m.purpose && <div className="text-xs text-gray-500 mt-1">{m.purpose}</div>}
            </div>
          ))}
        </div>
      </section>

      {/* 异常指标 */}
      {abnormalLabs.length > 0 && (
        <section>
          <h3 className="text-lg font-semibold mb-3">异常指标</h3>
          <div className="space-y-2">
            {abnormalLabs.map((l, i) => (
              <div key={i} className="bg-red-900/20 border border-red-800/30 rounded-lg p-3 flex justify-between">
                <div>
                  <span className="text-white">{l.test_name}</span>
                  <span className="ml-2 text-gray-400 text-sm">{l.test_date?.slice(0, 10)}</span>
                </div>
                <div className="text-right">
                  <span className={`font-bold ${l.flag === 'H' ? 'text-red-400' : 'text-yellow-400'}`}>
                    {l.value} {l.unit}
                  </span>
                  <span className="text-gray-500 text-xs ml-1">({l.ref_range})</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function TimelineTab({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="space-y-3">
      {events.map((e, i) => (
        <div key={i} className="bg-[var(--surface)] rounded-lg p-4 relative pl-8">
          {/* 时间线圆点 */}
          <div className="absolute left-3 top-4 w-2 h-2 rounded-full bg-[var(--primary)]" />
          {i < events.length - 1 && (
            <div className="absolute left-[13px] top-6 w-0.5 h-full bg-[var(--border)]" />
          )}
          <div className="flex justify-between items-start">
            <div>
              <div className="text-sm text-[var(--primary)]">{e.event_date?.slice(0, 10)}</div>
              <div className="text-white font-medium mt-1">{e.event_type}</div>
              <div className="text-gray-400 text-sm">{e.hospital} · {e.department}</div>
              {e.duration_days && e.duration_days > 1 && (
                <div className="text-xs text-yellow-400 mt-1">住院 {e.duration_days} 天</div>
              )}
            </div>
            {e.cost && (
              <div className="text-right">
                <div className="text-white font-medium">¥{e.cost.toLocaleString()}</div>
              </div>
            )}
          </div>
        </div>
      ))}
      {events.length === 0 && <div className="text-center py-8 text-gray-400">暂无临床事件记录</div>}
    </div>
  );
}

function MedicationsTab({ medications }: { medications: Medication[] }) {
  return (
    <div className="space-y-3">
      {medications.map((m, i) => (
        <div key={i} className="bg-[var(--surface)] rounded-lg p-4">
          <div className="flex justify-between items-start">
            <div>
              <span className="text-white font-medium text-lg">{m.medication_name}</span>
              <span className={`ml-2 text-xs px-2 py-0.5 rounded ${
                m.status === 'active'
                  ? 'text-green-400 bg-green-400/10'
                  : 'text-gray-400 bg-gray-400/10'
              }`}>
                {m.status === 'active' ? '使用中' : '已停用'}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 text-sm">
            <div><span className="text-gray-500">剂量:</span> <span className="text-white">{m.dose}</span></div>
            <div><span className="text-gray-500">途径:</span> <span className="text-white">{m.route}</span></div>
            <div><span className="text-gray-500">频率:</span> <span className="text-white">{m.frequency}</span></div>
            <div><span className="text-gray-500">用途:</span> <span className="text-white">{m.purpose}</span></div>
          </div>
          <div className="text-xs text-gray-500 mt-2">
            {m.start_date} ~ {m.end_date || '至今'}
          </div>
        </div>
      ))}
      {medications.length === 0 && <div className="text-center py-8 text-gray-400">暂无用药记录</div>}
    </div>
  );
}

function LabsTab({ labs }: { labs: LabResult[] }) {
  const grouped = labs.reduce<Record<string, LabResult[]>>((acc, l) => {
    const date = l.test_date?.slice(0, 10) || 'unknown';
    if (!acc[date]) acc[date] = [];
    acc[date].push(l);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {Object.entries(grouped).sort(([a], [b]) => b.localeCompare(a)).map(([date, results]) => (
        <div key={date}>
          <h3 className="text-sm font-medium text-[var(--primary)] mb-2">{date} 化验报告</h3>
          <div className="bg-[var(--surface)] rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border)] text-gray-400">
                  <th className="text-left p-2">项目</th>
                  <th className="text-right p-2">结果</th>
                  <th className="text-left p-2">参考范围</th>
                  <th className="text-center p-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className={`border-b border-[var(--border)] ${r.flag ? 'bg-red-900/10' : ''}`}>
                    <td className="p-2 text-white">{r.test_name}</td>
                    <td className="p-2 text-right">
                      <span className={r.flag ? (r.flag === 'H' ? 'text-red-400 font-bold' : 'text-yellow-400 font-bold') : 'text-white'}>
                        {v(r.value)} {r.unit}
                      </span>
                    </td>
                    <td className="p-2 text-gray-400">{r.ref_range}</td>
                    <td className="p-2 text-center">
                      {r.flag === 'H' && <span className="text-red-400 text-xs font-bold">↑ 偏高</span>}
                      {r.flag === 'L' && <span className="text-yellow-400 text-xs font-bold">↓ 偏低</span>}
                      {!r.flag && <span className="text-green-400 text-xs">正常</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
      {labs.length === 0 && <div className="text-center py-8 text-gray-400">暂无化验记录</div>}
    </div>
  );
}

function AnalysisTab({ analysis, analyzing, onAnalyze }: { analysis: AnalysisResult | null; analyzing: boolean; onAnalyze: () => void }) {
  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">AI 健康分析</h3>
        <button
          onClick={onAnalyze}
          disabled={analyzing}
          className="px-4 py-2 bg-[var(--primary)] text-black font-medium rounded-lg hover:opacity-90 disabled:opacity-50 text-sm"
        >
          {analyzing ? '分析中...' : '⚡ 重新分析'}
        </button>
      </div>

      {analysis ? (
        <div className="space-y-4">
          {analysis.summary && (
            <div className="bg-[var(--surface)] rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-2">综合评估</div>
              <div className="text-white leading-relaxed">{analysis.summary}</div>
              <div className="mt-2 text-xs text-gray-500">置信度: {(analysis.confidence * 100).toFixed(0)}%</div>
            </div>
          )}

          {analysis.concerns?.length > 0 && (
            <div className="bg-red-900/20 border border-red-800/30 rounded-lg p-4">
              <div className="text-sm text-red-400 mb-2">⚠ 风险提示</div>
              {analysis.concerns.map((c, i) => (
                <div key={i} className="text-white text-sm leading-relaxed">• {c}</div>
              ))}
            </div>
          )}

          {analysis.recommendations?.length > 0 && (
            <div className="bg-[var(--surface)] rounded-lg p-4">
              <div className="text-sm text-[var(--primary)] mb-2">💡 建议</div>
              {analysis.recommendations.map((r, i) => (
                <div key={i} className="text-white text-sm leading-relaxed mb-1">{i + 1}. {r}</div>
              ))}
            </div>
          )}

          {analysis.insights?.length > 0 && (
            <div className="bg-[var(--surface)] rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-2">健康洞察</div>
              {analysis.insights.map((ins, i) => (
                <div key={i} className="text-white text-sm leading-relaxed">• {ins}</div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="text-center py-12 text-gray-400">
          点击"重新分析"生成 AI 健康分析报告
        </div>
      )}
    </div>
  );
}
