import type { LessonSection, PracticeWord, Retry } from './instructions';
import type { CallLatency, LatencyResult } from './latency';
import { toThinkingGaps } from './thinkingGaps';
import { parseSummaryStatus, type SummaryStatus } from './summaryStatus';

export type WeakPoint = { pattern: string; example: string };
// 내 단어장에서 친구 통화·채팅에 보여 주는 단어와 저장한 문장. 서버가 아직 안 주는 동안은 없다.
export type NativeHint = { phrase: string; meaning: string };
export type Wordbook = {
  words: { lemma: string; gloss: string }[];
  phrases: { text: string; gloss: string }[];
  // 친구 통화·채팅에 줄 원어민 표현(서버가 통화마다 2개를 고른다). 단어장 공유 설정과 별개다.
  native?: NativeHint[];
};
export type LearnerProfile = {
  brief: string;
  updated: string | null;
  weak_points: WeakPoint[];
  next_goal: string;
  practice_words: PracticeWord[];
  interests?: string[];
  load_failed?: boolean;
  wordbook?: Wordbook;
  native_expressions?: NativeHint[];
};
// smalltalk(친구 통화)는 제한이 없어 null이다.
export type TimeLimits = { call: number; teachback: number; smalltalk: number | null };
export const DEFAULT_TIME_LIMITS: TimeLimits = { call: 600, teachback: 900, smalltalk: null };

export function parseTimeLimits(data: any): TimeLimits {
  const limits = data?.time_limits;
  const smalltalk = Number(limits?.smalltalk);
  return {
    call: Number(limits?.call) || DEFAULT_TIME_LIMITS.call,
    teachback: Number(limits?.teachback) || DEFAULT_TIME_LIMITS.teachback,
    smalltalk: smalltalk > 0 ? smalltalk : null,
  };
}
export type Lesson = {
  date: string;
  dates: string[];
  day_title?: string;
  sections: LessonSection[];
  hidden_count?: number;
};
// 예상 비용(USD). 모르는 쪽은 null, total은 아는 쪽의 합이다.
export type Cost = { live: number | null; tutoring: number | null; total: number | null };
// 한국어 표현과 영어 표현의 생각 방식 차이. word=단어를 몰랐음, framing=말하는 틀이 다름.
// detail(한국어 자세한 설명)·examples(영어 예문)는 새 통화에만 있다. 옛 통화는 note만 있다.
export type ThinkingGap = { korean: string; english: string; kind: 'word' | 'framing'; note: string; detail?: string; examples?: string[] };
// 통화 뒤 대화 상대가 보내는 메시지. 이번 통화에서 나온 표현만 담긴다.
export type FriendMessage = {
  opening: string;
  phrases: { phrase: string; note: string }[];
  next_time: string;
};
// 미국식으로 말하기: 학습자가 실제로 한 말(said)과 그 자리에서 미국에서 자연스러운 표현(natural), 왜 다른지(why)와 한국식 생각(korean_way).
export type UsStyleItem = { said: string; korean_way: string; natural: string; why: string };
export type Tutoring = {
  corrections: { said: string; better: string; why: string }[];
  good: { said: string; note: string }[];
  vocab: { word: string; meaning_ko: string; example: string; etymology: string }[];
  // 일반 튜터링에서는 항상 빈 목록이다. 옛 저장 파일에만 값이 있다(us_style가 대신한다).
  pragmatics: { pattern: string; note: string }[];
  us_style?: UsStyleItem[];
  retry: Retry;
  unanswered?: { question: string; teacher_said: string; cause: string; evidence: string }[];
  practice_used?: string[];
  readgloss?: { saved: number } | null;
  cost?: Cost | null;
  thinking_gaps?: ThinkingGap[];
  friend_message?: FriendMessage | null;
  // 서버가 이 분석에 쓴 통화 기록의 stem. 옛 응답에는 없다.
  stem?: string | null;
};

export type CallSummary = {
  stem: string;
  // 통화 정리(요약) 상태. 서버가 통화가 끝나면 스스로 정리를 건다.
  summary: SummaryStatus;
  started_at: string;
  mission: string;
  duration_sec: number;
  completed: boolean;
  has_tutoring: boolean;
  kind: 'teachback' | 'smalltalk' | 'call';
  voice?: string | null;
  partner?: string | null;
  cost?: Cost | null;
  latency?: CallLatency | null;
};
export type CallTotals = { calls: number; minutes: number; days: number; week: number };
export type Turn = { speaker: 'me' | 'partner'; text: string };
export function withSummary(call: CallSummary): CallSummary {
  return { ...call, summary: parseSummaryStatus(call.summary, call.has_tutoring) };
}

export type CallDetail = { call: CallSummary; tutoring: Tutoring | null; transcript: Turn[]; verbatim: string | null };

export type Clip = {
  id: string;
  title: string;
  channel: string;
  thumbnail: string;
  published?: string;
  start?: number;
  start_f?: number;
  end?: number;
  text?: string;
  phrase?: string;
  source?: 'db' | 'search';
};
// 저장한 단어·표현이 어느 영상 몇 초에서 나왔는지. 서버가 youtu.be/<video_id>?t=<t> 링크로 바꿔 readgloss에 남긴다.
export type SaveSource = { video_id: string; t: number; title: string };
export type ClipLine = { id: number; start: number; end: number; text: string };
export type ClipSegments = { lines: ClipLine[]; atId: number | null; hasMoreBefore: boolean; hasMoreAfter: boolean };
export type ClipStatus = 'ok' | 'no_key' | 'no_query' | 'error';
export type ClipResult = { query: string; clips: Clip[]; status: ClipStatus };

export type CultureBlend = { id: string; question: string; korea: string[]; us: string[] };
export type CultureBank = { country: 'US' | 'KR'; topic: string | null; text: string; source?: string };
export type CultureStatus = 'ok' | 'no_db' | 'no_terms';
export type CultureResult = { status: CultureStatus; blend: CultureBlend[]; bank: CultureBank[]; attribution: string };

export function formatUsd(n: number): string {
  return `$${n.toFixed(3)}`;
}

export function formatUsdShort(n: number): string {
  return `$${n.toFixed(n >= 0.01 ? 2 : 3)}`;
}

export type PartnerMemoryFact = { text: string; last_seen: string };
export type PartnerMemoryThread = { text: string; ko: string; last_seen: string };
export type PartnerMemorySelfStory = { story: string; progress: string; last_seen: string };
export type PartnerMemoryJoke = { text: string; last_seen: string };
export type PartnerMemoryEpisode = { date: string; mode: 'call' | 'chat'; summary: string };
export type PartnerMemory = {
  partner: string;
  updated: string;
  facts: PartnerMemoryFact[];
  threads: PartnerMemoryThread[];
  self_story: PartnerMemorySelfStory[];
  jokes: PartnerMemoryJoke[];
  episodes: PartnerMemoryEpisode[];
};
export type PartnerMemoryKind = 'facts' | 'threads' | 'self_story' | 'jokes' | 'episodes';

// 서버 응답(옛 v1 파일은 새 키가 없다)을 PartnerMemory로 맞춘다.
function toPartnerMemory(raw: any, id: string): PartnerMemory {
  const list = (v: unknown) => (Array.isArray(v) ? v : []);
  return {
    partner: String(raw?.partner ?? id),
    updated: String(raw?.updated ?? ''),
    facts: list(raw?.facts),
    threads: list(raw?.threads),
    self_story: list(raw?.self_story),
    jokes: list(raw?.jokes),
    episodes: list(raw?.episodes),
  };
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

// 친구가 기억하는 내용. 기억이 없으면 null이다.
export async function getPartnerMemory(id: string, signal?: AbortSignal): Promise<PartnerMemory | null> {
  let res: Response;
  try {
    res = await fetch(`/api/partners/${encodeURIComponent(id)}/memory`, { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('친구의 기억을 불러오지 못했어요.');
  }
  if (!res.ok) throw new Error(await errorMessage(res, '친구의 기억을 불러오지 못했어요.'));
  const data = await res.json();
  if (data?.status !== 'ok' || !data.memory) return null;
  return toPartnerMemory(data.memory, id);
}

export async function clearPartnerMemory(id: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/partners/${encodeURIComponent(id)}/memory`, { method: 'DELETE' });
  } catch {
    throw new Error('기억을 지우지 못했어요.');
  }
  if (!res.ok) throw new Error(await errorMessage(res, '기억을 지우지 못했어요.'));
}

// 화면에 보이던 항목과 서버의 항목이 달라졌을 때(서버가 409) 던진다. 화면은 기억을 다시 불러온다.
export class MemoryChangedError extends Error {
  constructor(message = '기억이 바뀌었어요.') {
    super(message);
    this.name = 'MemoryChangedError';
  }
}

// 기억 한 줄을 지우고 남은 기억을 돌려준다. text는 화면이 보던 항목의 문장이라, 서버가 그 자리의 문장과 다르면 409로 거절한다.
export async function forgetPartnerMemoryItem(id: string, kind: PartnerMemoryKind, index: number, text: string): Promise<PartnerMemory> {
  let res: Response;
  try {
    res = await fetch(`/api/partners/${encodeURIComponent(id)}/memory/${kind}/${index}?text=${encodeURIComponent(text)}`, { method: 'DELETE' });
  } catch {
    throw new Error('기억을 지우지 못했어요.');
  }
  if (res.status === 409) throw new MemoryChangedError();
  if (!res.ok) throw new Error(await errorMessage(res, '기억을 지우지 못했어요.'));
  const data = await res.json();
  return toPartnerMemory(data?.memory, id);
}

export type ChatMessage = { role: 'me' | 'friend'; text: string; at: string };

export async function getChat(id: string, signal?: AbortSignal): Promise<ChatMessage[]> {
  let res: Response;
  try {
    res = await fetch(`/api/chat/${encodeURIComponent(id)}`, { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('대화를 불러오지 못했어요.');
  }
  if (!res.ok) throw new Error(await errorMessage(res, '대화를 불러오지 못했어요.'));
  const data = await res.json();
  return Array.isArray(data?.messages) ? data.messages : [];
}

// 메시지를 보내고 친구의 답과 저장된 두 메시지를 받는다. 실패하면 서버에는 아무것도 남지 않는다.
export async function sendChat(id: string, instruction: string, message: string): Promise<{ reply: string; messages: ChatMessage[] }> {
  let res: Response;
  try {
    res = await fetch(`/api/chat/${encodeURIComponent(id)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction, message }),
    });
  } catch {
    throw new Error('서버에 연결하지 못했어요. 잠시 뒤에 다시 보내 주세요.');
  }
  if (!res.ok) throw new Error(await errorMessage(res, '메시지를 보내지 못했어요. 잠시 뒤에 다시 보내 주세요.'));
  const data = await res.json();
  return { reply: String(data?.reply ?? ''), messages: Array.isArray(data?.messages) ? data.messages : [] };
}

// 대화를 떠날 때 부른다. 탭을 닫는 중에도 나가도록 keepalive로 보내고, 실패해도 화면에는 영향이 없다.
export function closeChat(id: string): void {
  void fetch(`/api/chat/${encodeURIComponent(id)}/close`, {
    method: 'POST',
    keepalive: true,
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).catch(() => {});
}

export async function getTimeLimits(): Promise<TimeLimits> {
  try {
    const sentAt = Date.now();
    const res = await fetch('/api/status');
    const serverDate = Date.parse(res.headers.get('date') || '');
    if (!Number.isNaN(serverDate)) clockOffsetMs = serverDate - (sentAt + Date.now()) / 2;
    const data = await res.json();
    return parseTimeLimits(data);
  } catch {
    return DEFAULT_TIME_LIMITS;
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

export async function saveWord(body: { word: string; lemma: string; gloss: string; sentence: string; source?: SaveSource }): Promise<void> {
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

function toFriendMessage(v: unknown): FriendMessage | null {
  if (!v || typeof v !== 'object') return null;
  const m = v as Record<string, unknown>;
  const text = (x: unknown) => (typeof x === 'string' ? x : '');
  const phrases = (Array.isArray(m.phrases) ? m.phrases : [])
    .filter((p): p is Record<string, unknown> => !!p && typeof p === 'object' && typeof (p as Record<string, unknown>).phrase === 'string')
    .map((p) => ({ phrase: text(p.phrase), note: text(p.note) }))
    .filter((p) => p.phrase.trim());
  return phrases.length ? { opening: text(m.opening), phrases, next_time: text(m.next_time) } : null;
}

function toTutoring(data: Record<string, unknown>): Tutoring {
  const list = (v: unknown) => (Array.isArray(v) ? v : []);
  return {
    corrections: list(data.corrections),
    good: list(data.good),
    vocab: list(data.vocab),
    pragmatics: list(data.pragmatics),
    us_style: list(data.us_style).filter(
      (u): u is UsStyleItem => !!u && typeof u.said === 'string' && typeof u.natural === 'string' && !!u.natural.trim(),
    ).map((u) => ({ said: u.said, korean_way: typeof u.korean_way === 'string' ? u.korean_way : '', natural: u.natural, why: typeof u.why === 'string' ? u.why : '' })),
    retry: (data.retry as Retry) || {},
    unanswered: list(data.unanswered),
    practice_used: list(data.practice_used),
    readgloss: (data.readgloss as Tutoring['readgloss']) ?? null,
    cost: (data.cost as Cost | null | undefined) ?? null,
    thinking_gaps: toThinkingGaps(data.thinking_gaps),
    friend_message: toFriendMessage(data.friend_message),
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
  // 이 통화의 응답 속도 측정값. 서버가 같은 요청 안에서 통화 기록에 저장한다.
  latency?: LatencyResult;
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
    calls: Array.isArray(data?.calls) ? data.calls.map(withSummary) : [],
  };
}

// 요약이 없거나 실패한 통화의 정리를 서버에서 (다시) 시작한다. 이미 돌고 있으면 새로 걸지 않는다.
export async function startSummary(stem: string): Promise<SummaryStatus> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}/summary`, { method: 'POST' });
  if (!res.ok) throw new Error(await errorMessage(res, '정리를 시작하지 못했어요.'));
  const data = await res.json();
  return parseSummaryStatus(data?.summary);
}

export async function getCall(stem: string, signal?: AbortSignal): Promise<CallDetail> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '통화 기록을 불러오지 못했어요.'));
  const data = await res.json();
  return {
    call: withSummary(data.call),
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

// 자막 DB에서 영상의 at초 앞뒤 줄. 없거나 실패하면 던진다(재생기는 일반 재생으로 열린다).
export async function getClipSegments(videoId: string, at: number, signal?: AbortSignal): Promise<ClipSegments> {
  const res = await fetch(`/api/clips/segments?video_id=${encodeURIComponent(videoId)}&at=${at}`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '자막 줄을 불러오지 못했어요.'));
  const data = await res.json();
  const lines: ClipLine[] = (Array.isArray(data?.lines) ? data.lines : []).filter(
    (l: any) => Number.isFinite(l?.id) && Number.isFinite(l?.start) && Number.isFinite(l?.end) && typeof l?.text === 'string',
  );
  return {
    lines,
    atId: Number.isFinite(data?.at_id) ? data.at_id : null,
    hasMoreBefore: data?.has_more_before === true,
    hasMoreAfter: data?.has_more_after === true,
  };
}

// 문화 DB가 없거나 검색어가 없으면 서버가 200으로 status만 다르게 준다. 화면은 ok일 때만 보여 준다.
export async function getCallCulture(stem: string, signal?: AbortSignal): Promise<CultureResult> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}/culture`, { signal });
  if (!res.ok) throw new Error(await errorMessage(res, '한국·미국 차이를 불러오지 못했어요.'));
  const data = await res.json();
  const status: CultureStatus = data?.status === 'ok' ? 'ok' : data?.status === 'no_terms' ? 'no_terms' : 'no_db';
  return {
    status,
    blend: Array.isArray(data?.blend) ? data.blend : [],
    bank: Array.isArray(data?.bank) ? data.bank : [],
    attribution: typeof data?.attribution === 'string' ? data.attribution : '',
  };
}
