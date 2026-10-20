// 저장된 통화 다시 하기: 통화 기록에서 단계(상대 말 / 내 차례)를 만들고, 내가 말한 문장을 목표 문장과 단어 단위로 비교한다.
// 서버에 새 통화를 걸지 않는다. 상대 말은 저장된 그대로 같은 목소리로 읽어 준다(POST /api/tts).

import { PARK_ID, PARTNERS, partnerById, type Partner } from './partners';

export type Correction = { said: string; better: string; why: string };

export type PartnerStep = { kind: 'partner'; text: string };
export type LearnerStep = {
  kind: 'me';
  /** 통화 때 한 말(잡음 표시를 지운 것) */
  original: string;
  /** 이번에 말할 문장: 맞는 교정의 better, 없으면 통화 때 한 말 */
  target: string;
  /** 교정 이유(없으면 빈 문자열) */
  why: string;
  /** 교정으로 바뀐 문장인지 */
  corrected: boolean;
  /** 영어로 따라 말할 수 있는 문장인지(한글이 섞였거나 영어 글자가 없으면 false) */
  speakable: boolean;
};
export type ReplayStep = PartnerStep | LearnerStep;

export type ReplayData = {
  stem: string;
  mission: string;
  startedAt: string;
  /** 통화 머리글의 Gemini Live 목소리. 옛 기록에는 없다 */
  voice: string | null;
  steps: ReplayStep[];
};

const MIN_OVERLAP = 0.5;
const FALLBACK_VOICE = 'Kore'; // Ms. Park

const WORD = /[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu;
const HANGUL = /[\u3131-\u318e\uac00-\ud7a3]/;
const LATIN = /[A-Za-z]/;

export function words(text: string): string[] {
  return (text.match(WORD) ?? []).map((w) => w.toLowerCase().replace(/’/g, "'"));
}

/** 받아쓰기 잡음 표시({}, <...>, [...])를 지우고 공백을 정리한다. */
export function cleanLine(text: string): string {
  return text
    .replace(/\{[^}]*\}|<[^>]*>|\[[^\]]*\]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function overlap(said: string, turn: string): { score: number; tie: number } {
  const a = words(said);
  const b = new Set(words(turn));
  if (!a.length || !b.size) return { score: 0, tie: 0 };
  const set = new Set(a);
  let common = 0;
  for (const w of set) if (b.has(w)) common++;
  return { score: common / set.size, tie: common / (set.size + b.size - common) };
}

/** 가장 비슷한 교정을 고른다. 겹침이 0.5 미만이면 null. */
export function pickCorrection(turn: string, corrections: Correction[], used: Set<number>): number | null {
  let best: number | null = null;
  let bestScore = MIN_OVERLAP - Number.EPSILON;
  let bestTie = -1;
  corrections.forEach((c, i) => {
    if (used.has(i)) return;
    const { score, tie } = overlap(c.said, turn);
    if (score > bestScore || (score === bestScore && tie > bestTie)) {
      best = i;
      bestScore = score;
      bestTie = tie;
    }
  });
  return best;
}

function replaceFragment(turn: string, said: string, better: string): string | null {
  const needle = cleanLine(said).replace(/[.!?]+$/, '');
  if (!needle) return null;
  const at = turn.toLowerCase().indexOf(needle.toLowerCase());
  if (at < 0) return null;
  const tail = turn.slice(at + needle.length);
  return (turn.slice(0, at) + better.replace(/[.!?]+$/, '') + tail).replace(/\s+/g, ' ').trim();
}

/** 통화 전문과 튜터링 교정으로 단계를 만든다. 순수 함수. */
export function buildSteps(transcript: { speaker: string; text: string }[], corrections: Correction[]): ReplayStep[] {
  const used = new Set<number>();
  const steps: ReplayStep[] = [];
  for (const turn of transcript) {
    const text = cleanLine(turn.text);
    if (!text) continue;
    if (turn.speaker !== 'me') {
      steps.push({ kind: 'partner', text });
      continue;
    }
    const pick = pickCorrection(text, corrections, used);
    let target = text;
    let why = '';
    let corrected = false;
    if (pick !== null) {
      used.add(pick);
      const c = corrections[pick];
      const better = cleanLine(c.better);
      if (better) {
        // 교정이 문장의 일부(said)만 고친 것이면 그 부분만 바꿔 문장 전체를 말하게 한다.
        const whole = overlap(text, c.said).score >= MIN_OVERLAP;
        target = (!whole && replaceFragment(text, c.said, better)) || better;
        // 한글이 남았으면(말하지 못해 한국어로 섞은 부분) better 문장만 쓴다.
        if (HANGUL.test(target) && !HANGUL.test(better)) target = better;
        why = c.why;
        corrected = true;
      }
    }
    steps.push({
      kind: 'me',
      original: text,
      target,
      why,
      corrected,
      speakable: LATIN.test(target) && !HANGUL.test(target),
    });
  }
  return steps;
}

/** 목소리 이름에 맞는 대화 상대. 모르는 목소리나 옛 기록은 Ms. Park. */
export function partnerForVoice(voice: string | null): Partner {
  return PARTNERS.find((p) => p.voice === voice) ?? partnerById(PARK_ID);
}

export type DiffOp = { kind: 'same' | 'missing' | 'extra'; word: string };

/** 목표 문장과 들린 문장을 단어 단위로 비교한다(LCS). missing: 목표에만 있음, extra: 들린 쪽에만 있음. */
export function diffWords(target: string, heard: string): DiffOp[] {
  const t = target.match(WORD) ?? [];
  const h = heard.match(WORD) ?? [];
  const norm = (w: string) => w.toLowerCase().replace(/’/g, "'");
  const n = t.length;
  const m = h.length;
  const lcs = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = norm(t[i]) === norm(h[j]) ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (norm(t[i]) === norm(h[j])) {
      ops.push({ kind: 'same', word: t[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      ops.push({ kind: 'missing', word: t[i++] });
    } else {
      ops.push({ kind: 'extra', word: h[j++] });
    }
  }
  while (i < n) ops.push({ kind: 'missing', word: t[i++] });
  while (j < m) ops.push({ kind: 'extra', word: h[j++] });
  return ops;
}

export function isExact(ops: DiffOp[]): boolean {
  return ops.every((o) => o.kind === 'same');
}

async function errorText(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail && typeof body.detail === 'string') return body.detail;
  } catch {
    // JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export function buildReplay(data: unknown, stem: string): ReplayData {
  const d = (data ?? {}) as {
    call?: { mission?: unknown; started_at?: unknown; voice?: unknown };
    transcript?: unknown;
    tutoring?: { corrections?: unknown } | null;
  };
  const transcript = (Array.isArray(d.transcript) ? d.transcript : []).filter(
    (t): t is { speaker: string; text: string } => !!t && typeof (t as { text?: unknown }).text === 'string' && typeof (t as { speaker?: unknown }).speaker === 'string',
  );
  const raw = Array.isArray(d.tutoring?.corrections) ? (d.tutoring?.corrections as unknown[]) : [];
  const corrections: Correction[] = raw
    .filter((c): c is Correction => !!c && typeof (c as Correction).said === 'string' && typeof (c as Correction).better === 'string')
    .map((c) => ({ said: c.said, better: c.better, why: typeof c.why === 'string' ? c.why : '' }));
  return {
    stem,
    mission: typeof d.call?.mission === 'string' ? d.call.mission : '',
    startedAt: typeof d.call?.started_at === 'string' ? d.call.started_at : '',
    voice: typeof d.call?.voice === 'string' && d.call.voice ? d.call.voice : null,
    steps: buildSteps(transcript, corrections),
  };
}

export async function loadReplay(stem: string, signal?: AbortSignal): Promise<ReplayData> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}`, { signal });
  if (!res.ok) throw new Error(await errorText(res, '통화 기록을 불러오지 못했어요.'));
  return buildReplay(await res.json(), stem);
}

/** 상대 말을 통화 때 목소리로 읽은 WAV. 서버가 같은 문장은 캐시해 둔다. */
export async function fetchTts(text: string, voice: string | null, signal?: AbortSignal): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 500), voice: voice ?? FALLBACK_VOICE }),
      signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (!res.ok) throw new Error(await errorText(res, '목소리를 만들지 못했어요. 잠시 후 다시 눌러 주세요.'));
  return res.blob();
}
