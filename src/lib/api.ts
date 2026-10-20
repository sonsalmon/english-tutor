import type { LessonSection, PracticeWord, Retry } from './instructions';

export type WeakPoint = { pattern: string; example: string };
export type LearnerProfile = {
  brief: string;
  updated: string | null;
  weak_points: WeakPoint[];
  next_goal: string;
  practice_words: PracticeWord[];
  interests?: string[];
  load_failed?: boolean;
};
export type TimeLimits = { call: number; teachback: number; smalltalk: number };
export type Lesson = {
  date: string;
  dates: string[];
  day_title?: string;
  sections: LessonSection[];
  hidden_count?: number;
};
// 예상 비용(USD). 모르는 쪽은 null, total은 아는 쪽의 합이다.
export type Cost = { live: number | null; tutoring: number | null; total: number | null };
export type Tutoring = {
  corrections: { said: string; better: string; why: string }[];
  good: { said: string; note: string }[];
  vocab: { word: string; meaning_ko: string; example: string; etymology: string }[];
  pragmatics: { pattern: string; note: string }[];
  retry: Retry;
  unanswered?: { question: string; teacher_said: string; cause: string; evidence: string }[];
  practice_used?: string[];
  readgloss?: { saved: number } | null;
  cost?: Cost | null;
  // 서버가 이 분석에 쓴 통화 기록의 stem. 옛 응답에는 없다.
  stem?: string | null;
};

export type CallSummary = {
  stem: string;
  started_at: string;
  mission: string;
  duration_sec: number;
  completed: boolean;
  has_tutoring: boolean;
  kind: 'teachback' | 'smalltalk' | 'call';
  voice?: string | null;
  cost?: Cost | null;
};
export type CallTotals = { calls: number; minutes: number; days: number; week: number };
export type Turn = { speaker: 'me' | 'partner'; text: string };
export type CallDetail = { call: CallSummary; tutoring: Tutoring | null; transcript: Turn[]; verbatim: string | null };

export type Clip = {
  id: string;
  title: string;
  channel: string;
  thumbnail: string;
  published?: string;
  start?: number;
  text?: string;
  phrase?: string;
  source?: 'db' | 'search';
};
export type ClipStatus = 'ok' | 'no_key' | 'no_query' | 'error';
export type ClipResult = { query: string; clips: Clip[]; status: ClipStatus };

export function formatUsd(n: number): string {
  return `$${n.toFixed(3)}`;
}

export function formatUsdShort(n: number): string {
  return `$${n.toFixed(n >= 0.01 ? 2 : 3)}`;
}

export type WordInfo = { word: string; lemma: string; gloss: string; senses: string[]; pos?: string };

// readgloss가 꺼져 있을 때(503)만 던지는 오류. 화면이 다른 실패와 구분해 안내 문구를 보여 준다.
export class ReadglossOffError extends Error {
  constructor(message = 'readgloss가 꺼져 있어 뜻을 찾지 못했어요.') {
    super(message);
    this.name = 'ReadglossOffError';
  }
}

const EMPTY_PROFILE: LearnerProfile = { brief: '', updated: null, weak_points: [], next_goal: '', practice_words: [] };

// 폰 시계가 Mac과 다르면 튜터링이 "이번 통화 전문"을 못 찾는다(서버는 파일 시각과 started_at을 비교).
// 서버 응답의 Date 헤더로 차이를 재서 통화 시각을 서버 시계 기준으로 맞춘다.
let clockOffsetMs = 0;

export function serverNow(): number {
  return Date.now() + clockOffsetMs;
}

async function errorMessage(res: Response, fallback?: string): Promise<string | undefined> {
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
    return {
      call: Number(data?.time_limits?.call) || 600,
      teachback: Number(data?.time_limits?.teachback) || 900,
      smalltalk: Number(data?.time_limits?.smalltalk) || 300,
    };
  } catch {
    return { call: 600, teachback: 900, smalltalk: 300 };
  }
}

async function postWord(path: string, body: unknown, fallback: string, signal?: AbortSignal): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error(fallback);
  }
  if (res.status === 503) throw new ReadglossOffError(await errorMessage(res, undefined));
  if (!res.ok) throw new Error(await errorMessage(res, fallback));
  return res;
}

export async function lookupWord(word: string, signal?: AbortSignal): Promise<WordInfo> {
  const res = await postWord('/api/word', { word }, '뜻을 찾지 못했어요.', signal);
  const data = await res.json();
  return {
    word: String(data?.word ?? word),
    lemma: String(data?.lemma ?? word),
    gloss: String(data?.gloss ?? ''),
    senses: Array.isArray(data?.senses) ? data.senses.map(String) : [],
    pos: data?.pos ? String(data.pos) : undefined,
  };
}

export async function saveWord(body: { word: string; lemma: string; gloss: string; sentence: string }): Promise<void> {
  await postWord('/api/word/save', body, '단어를 저장하지 못했어요.');
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
    cost: (data.cost as Cost | null | undefined) ?? null,
    stem: typeof data.stem === 'string' && data.stem ? data.stem : null,
  };
}

// 튜터링이 실패해도 서버가 stem을 알려 주면 담아 둔다. 없으면 null.
export class TutoringError extends Error {
  stem: string | null;
  constructor(message: string, stem: string | null = null) {
    super(message);
    this.name = 'TutoringError';
    this.stem = stem;
  }
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
  if (!res.ok) {
    let stem: string | null = null;
    let detail: string | undefined;
    try {
      const body = await res.json();
      if (typeof body?.stem === 'string' && body.stem) stem = body.stem;
      if (body?.detail) detail = String(body.detail);
    } catch {
      // 본문이 JSON이 아니면 기본 문구를 쓴다.
    }
    throw new TutoringError(detail ?? '튜터링 분석에 실패했어요.', stem);
  }
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
  return {
    call: data.call,
    tutoring: data.tutoring ? toTutoring(data.tutoring) : null,
    transcript: Array.isArray(data.transcript) ? data.transcript : [],
    verbatim: typeof data.verbatim === 'string' && data.verbatim.trim() ? data.verbatim : null,
  };
}

export async function getCallClips(stem: string, signal?: AbortSignal): Promise<ClipResult> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}/clips`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '관련 영상을 불러오지 못했어요.'));
  const data = await res.json();
  const status: ClipStatus = ['ok', 'no_key', 'no_query'].includes(data?.status) ? data.status : 'error';
  return {
    query: typeof data?.query === 'string' ? data.query : '',
    clips: Array.isArray(data?.clips) ? data.clips : [],
    status,
  };
}
