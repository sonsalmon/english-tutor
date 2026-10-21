import { useEffect } from 'react';
import type { Clip } from './api';

export type ReviewKind = 'correction' | 'us_style' | 'vocab' | 'good' | 'thinking_gap';
export type ReviewState = 'saved' | 'known' | 'misheard';
export type ReviewItems = Record<string, ReviewState>;

const STATES: readonly string[] = ['saved', 'known', 'misheard'];

// 서버 known.make_key와 같은 규칙: 소문자, 영어 낱말·숫자·어포스트로피만 남기고 공백을 정리한다.
export function textKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/\u2019/g, "'")
    .replace(/[^a-z0-9' ]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ');
}

// 서버 review.item_key와 같은 이름: "<종류>:<정리한 글>".
export const reviewKey = (kind: ReviewKind, text: string): string => `${kind}:${textKey(text)}`;

export const isFlagged = (state: ReviewState | undefined): boolean => state === 'known' || state === 'misheard';

export function withState(items: ReviewItems, key: string, state: ReviewState | null | undefined): ReviewItems {
  const next = { ...items };
  if (state) next[key] = state;
  else delete next[key];
  return next;
}

async function failMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // 본문이 JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export async function getReview(stem: string, signal?: AbortSignal): Promise<ReviewItems> {
  const res = await fetch(`/api/calls/${encodeURIComponent(stem)}/review`, { signal });
  if (!res.ok) throw new Error(await failMessage(res, '표시한 항목을 불러오지 못했어요.'));
  const data = await res.json();
  const out: ReviewItems = {};
  if (data?.items && typeof data.items === 'object') {
    for (const [key, value] of Object.entries(data.items as Record<string, unknown>)) {
      if (typeof value === 'string' && STATES.includes(value)) out[key] = value as ReviewState;
    }
  }
  return out;
}

export async function flagReview(body: { stem: string; kind: ReviewKind; text: string; state: ReviewState | null }): Promise<void> {
  const res = await fetch('/api/review/flag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await failMessage(res, '표시하지 못했어요.'));
}

// 화면을 떠나는 순간에도 요청이 끝까지 가도록 keepalive로 보낸다. 실패해도 서버가 15분 뒤에 같은 일을 한다.
export function finishReview(stem: string): void {
  fetch(`/api/calls/${encodeURIComponent(stem)}/review/finish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    keepalive: true,
  }).catch(() => {});
}

// 요약·통화 내역 상세를 떠날 때(화면 닫힘, 페이지 숨김, 앱 전환) 검토가 끝났다고 서버에 알린다. 학습자 카드는 그때 갱신된다.
export function useFinishReview(stem?: string | null): void {
  useEffect(() => {
    if (!stem) return;
    const onHidden = () => {
      if (document.visibilityState === 'hidden') finishReview(stem);
    };
    const onPageHide = () => finishReview(stem);
    window.addEventListener('pagehide', onPageHide);
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      window.removeEventListener('pagehide', onPageHide);
      document.removeEventListener('visibilitychange', onHidden);
      finishReview(stem);
    };
  }, [stem]);
}

export type PhraseClipResult = { status: 'ok' | 'no_db' | 'no_query'; clips: Clip[] };

// 표현을 말하는 순간을 자막 DB에서 찾는다. 실패하면 던지고, 화면은 이 구역만 숨긴다.
export async function getPhraseClips(phrase: string, limit = 3, signal?: AbortSignal): Promise<PhraseClipResult> {
  const res = await fetch(`/api/clips/phrase?q=${encodeURIComponent(phrase)}&limit=${limit}`, { signal });
  if (!res.ok) throw new Error(await failMessage(res, '예시 클립을 불러오지 못했어요.'));
  const data = await res.json();
  const status = data?.status === 'ok' || data?.status === 'no_db' ? data.status : 'no_query';
  return { status, clips: Array.isArray(data?.clips) ? data.clips : [] };
}
