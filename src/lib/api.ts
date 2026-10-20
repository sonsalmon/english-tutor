import type { LessonSection, Retry } from './instructions';

export type WeakPoint = { pattern: string; example: string };
export type LearnerProfile = { brief: string; updated: string | null; weak_points: WeakPoint[]; next_goal: string };
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
};

const EMPTY_PROFILE: LearnerProfile = { brief: '', updated: null, weak_points: [], next_goal: '' };

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
    if (!res.ok) return EMPTY_PROFILE;
    return { ...EMPTY_PROFILE, ...(await res.json()) };
  } catch {
    return EMPTY_PROFILE;
  }
}

export async function getTimeLimits(): Promise<TimeLimits> {
  try {
    const res = await fetch('/api/status');
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

export async function requestTutoring(body: { started_at: number; mode?: 'teachback'; lesson_date?: string }): Promise<Tutoring> {
  const res = await fetch('/api/tutor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res, '튜터링 분석에 실패했어요.'));
  const data = await res.json();
  const list = (v: unknown) => (Array.isArray(v) ? v : []);
  return {
    corrections: list(data.corrections),
    good: list(data.good),
    vocab: list(data.vocab),
    pragmatics: list(data.pragmatics),
    retry: data.retry || {},
    unanswered: list(data.unanswered),
  };
}
