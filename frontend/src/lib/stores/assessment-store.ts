// 跨领域评估 (康复 + 营养 + 运动) Store
// 2026-07-07 新增

import { create } from 'zustand';
import { api } from '../api';

export interface AssessmentStartResult {
  session_id: string;
  current_state: Record<string, unknown>;
  missing_dimensions: string[];
}

export interface AssessmentQuestion {
  question: string;
  options: string[];
  is_final: boolean;
  dimension: string;
}

export interface AssessmentResult {
  scores: { rehab: number; nutrition: number; training: number };
  advice: string;
  summary: Record<string, unknown>;
}

interface AssessmentState {
  // 状态
  sessionId: string | null;
  currentState: Record<string, unknown>;
  missingDimensions: string[];
  currentQuestion: AssessmentQuestion | null;
  answers: { dimension: string; answer: string }[];
  loading: boolean;
  error: string | null;

  // 结果
  result: AssessmentResult | null;
  resultError: string | null;

  // 动作
  start: () => Promise<void>;
  answer: (selected: string) => Promise<void>;
  complete: () => Promise<void>;
  reset: () => void;
}

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  currentState: {},
  missingDimensions: [],
  currentQuestion: null,
  answers: [],
  loading: false,
  error: null,
  result: null,
  resultError: null,

  start: async () => {
    set({ loading: true, error: null, result: null, resultError: null });
    try {
      const data = await api.assessmentStart();
      // 取第一个待评估维度,作为初始题
      const firstDim = data.missing_dimensions[0] || 'rehab';
      const q = await api.assessmentQuestion(data.session_id, '', firstDim);
      // 注意:第一次 question 调用传空 answer 也会被记入 answers (服务端逻辑)
      set({
        sessionId: data.session_id,
        currentState: data.current_state,
        missingDimensions: data.missing_dimensions,
        currentQuestion: { ...q, dimension: firstDim },
        loading: false,
      });
    } catch (e: unknown) {
      set({
        error: e instanceof Error ? e.message : '启动失败',
        loading: false,
      });
    }
  },

  answer: async (selected: string) => {
    const { sessionId, currentQuestion, answers } = get();
    if (!sessionId || !currentQuestion) return;
    set({ loading: true, error: null });
    try {
      const newAnswers = [
        ...answers,
        { dimension: currentQuestion.dimension, answer: selected },
      ];
      // 取下一题(同维度或下一维度)
      const q = await api.assessmentQuestion(
        sessionId,
        selected,
        currentQuestion.dimension,
      );
      set({
        currentQuestion: q,
        answers: newAnswers,
        loading: false,
      });
    } catch (e: unknown) {
      set({
        error: e instanceof Error ? e.message : '获取问题失败',
        loading: false,
      });
    }
  },

  complete: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const result = await api.assessmentComplete(sessionId);
      set({ result, loading: false });
    } catch (e: unknown) {
      set({
        resultError: e instanceof Error ? e.message : '生成评估失败',
        loading: false,
      });
    }
  },

  reset: () =>
    set({
      sessionId: null,
      currentState: {},
      missingDimensions: [],
      currentQuestion: null,
      answers: [],
      loading: false,
      error: null,
      result: null,
      resultError: null,
    }),
}));
