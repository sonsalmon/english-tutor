import { ReadglossOffError } from './api';

export type WordStatus = 'due' | 'done' | 'learning';
export type WordbookWord = { lemma: string; word: string; gloss: string; ts: number; status: WordStatus };
export type WordbookPhrase = { id: string; text: string; gloss: string; ts: number };
export type WordbookData = { words: WordbookWord[]; phrases: WordbookPhrase[] };

export const WORD_STATUS_LABEL: Record<WordStatus, string> = { due: '복습할 차례', done: '복습 끝', learning: '익히는 중' };

// readgloss가 꺼져 있으면(503) ReadglossOffError를 던진다. 나머지 실패는 일반 Error다.
export async function getWordbookData(signal?: AbortSignal): Promise<WordbookData> {
  let res: Response;
  try {
    res = await fetch('/api/wordbook', { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (res.status === 503) throw new ReadglossOffError('readgloss가 꺼져 있어 단어장을 불러오지 못했어요.');
  if (!res.ok) throw new Error('단어장을 불러오지 못했어요.');
  const data = await res.json();
  const status = (s: unknown): WordStatus => (s === 'due' || s === 'done' ? s : 'learning');
  return {
    words: (Array.isArray(data?.words) ? data.words : []).map((w: any) => ({
      lemma: String(w?.lemma ?? ''),
      word: String(w?.word ?? w?.lemma ?? ''),
      gloss: String(w?.gloss ?? ''),
      ts: Number(w?.ts) || 0,
      status: status(w?.status),
    })),
    phrases: (Array.isArray(data?.phrases) ? data.phrases : []).map((p: any) => ({
      id: String(p?.id ?? p?.text ?? ''),
      text: String(p?.text ?? ''),
      gloss: String(p?.gloss ?? ''),
      ts: Number(p?.ts) || 0,
    })),
  };
}

// 검색어로 단어·구를 거른다. 영어와 한국어 뜻 어느 쪽이든 맞으면 남긴다.
export function filterWordbook<T extends { gloss: string }>(items: T[], query: string, textOf: (item: T) => string): T[] {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => textOf(item).toLowerCase().includes(q) || item.gloss.toLowerCase().includes(q));
}
