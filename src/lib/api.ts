import type { LessonSection, PracticeWord, Retry } from './instructions';

export type WeakPoint = { pattern: string; example: string };
export type LearnerProfile = {
  brief: string;
  updated: string | null;
  weak_points: WeakPoint[];
  next_goal: string;
  practice_words: PracticeWord[];
  load_failed?: boolean;
};
export type TimeLimits = { call: number; teachback: number };
export type Lesson = {
  date: string;
  dates: string[];
  day_title?: string;
  sections: LessonSection[];
  hidden_count?: number;
};
export type Tutoring = {
  corrections: { said: string; better: string; why: string }[];
  good: { said: string; note: string }[];
  vocab: { word: string; meaning_ko: string; example: string; etymology: string }[];
  pragmatics: { pattern: string; note: string }[];
  retry: Retry;
  unanswered?: { question: string; teacher_said: string; cause: string; evidence: string }[];
  practice_used?: string[];
  readgloss?: { saved: number } | null;
};

export type CallSummary = {
  stem: string;
  started_at: string;
  mission: string;
  duration_sec: number;
  completed: boolean;
  has_tutoring: boolean;
  kind: 'teachback' | 'call';
};
export type CallTotals = { calls: number; minutes: number; days: number; week: number };
export type CallDetail = { call: CallSummary; tutoring: Tutoring | null };

const EMPTY_PROFILE: LearnerProfile = { brief: '', updated: null, weak_points: [], next_goal: '', practice_words: [] };

// 폰 시계가 Mac과 다르면 튜터링이 "이번 통화 전문"을 못 찾는다(서버는 파일 시각과 started_at을 비교).
// 서버 응답의 Date 헤더로 차이를 재서 통화 시각을 서버 시계 기준으로 맞춘다.
let clockOffsetMs = 0;

export function serverNow(): number {
  return Date.now() + clockOffsetMs;
}

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // 본문이 JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export async function getLearnerProfile(): Promise<LearnerProfile> {
  try {
    const res = await fetch('/api/learner-profile');
    if (!res.ok) return { ...EMPTY_PROFILE, load_failed: true };
    return { ...EMPTY_PROFILE, ...(await res.json()) };
  } catch {
    return { ...EMPTY_PROFILE, load_failed: true };
  }
}

export async function getTimeLimits(): Promise<TimeLimits> {
  try {
    const sentAt = Date.now();
    const res = await fetch('/api/status');
    const serverDate = Date.parse(res.headers.get('date') || '');
    if (!Number.isNaN(serverDate)) clockOffsetMs = serverDate - (sentAt + Date.now()) / 2;
    const data = await res.json();
    return { call: Number(data?.time_limits?.call) || 600, teachback: Number(data?.time_limits?.teachback) || 900 };
  } catch {
    return { call: 600, teachback: 900 };
  }
}

export async function getLesson(date?: string, signal?: AbortSignal): Promise<Lesson> {
  const res = await fetch(date ? `/api/lesson?date=${encodeURIComponent(date)}` : '/api/lesson', { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '수업 기록을 불러오지 못했어요.'));
  const data = await res.json();
  return {
    date: data.date || '',
    dates: Array.isArray(data.dates) ? data.dates : [],
    day_title: data.day_title,
    sections: Array.isArray(data.sections) ? data.sections : [],
    hidden_count: Number(data.hidden_count) || 0,
  };
}

function toTutoring(data: Record<string, unknown>): Tutoring {
  const list = (v: unknown) => (Array.isArray(v) ? v : []);
  return {
    corrections: list(data.corrections),
    good: list(data.good),
    vocab: list(data.vocab),
    pragmatics: list(data.pragmatics),
    retry: (data.retry as Retry) || {},
    unanswered: list(data.unanswered),
    practice_used: list(data.practice_used),
    readgloss: (data.readgloss as Tutoring['readgloss']) ?? null,
  };
}

export async function requestTutoring(body: {
  started_at: number;
  mode?: 'teachback';
  lesson_date?: string;
  practice_words?: string[];
}): Promise<Tutoring> {
  const res = await fetch('/api/tutor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res, '튜터링 분석에 실패했어요.'));
  return toTutoring(await res.json());
}

export async function getCalls(limit = 50, signal?: AbortSignal): Promise<{ totals: CallTotals; calls: CallSummary[] }> {
  const res = await fetch(`/api/calls?limit=${limit}`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '통화 기록을 불러오지 못했어요.'));
  const data = await res.json();
  return {
    totals: {
      calls: Number(data?.totals?.calls) || 0,
      minutes: Number(data?.totals?.minutes) || 0,
      days: Number(data?.totals?.days) || 0,
      week: Number(data?.totals?.week) || 0,
    },
    calls: Array.isArray(data?.calls) ? data.calls : [],
  };
}

export async function getCall(stem: string, signal?: AbortSignal): Promise<CallDetail> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '통화 기록을 불러오지 못했어요.'));
  const data = await res.json();
  return { call: data.call, tutoring: data.tutoring ? toTutoring(data.tutoring) : null };
}
