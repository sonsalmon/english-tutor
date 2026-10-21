import { ReadglossOffError, type SaveSource } from './api';

// readgloss가 꺼져 있을 때(503)는 ReadglossOffError, 나머지 실패는 일반 Error로 던진다.
async function postPhrase(path: string, body: unknown, fallback: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(fallback);
  }
  if (res.status === 503) throw new ReadglossOffError('readgloss가 꺼져 있어 카드로 저장할 수 없어요.');
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const data = await res.json();
      if (data?.detail) detail = String(data.detail);
    } catch {
      // 본문이 JSON이 아니면 기본 문구를 쓴다.
    }
    throw new Error(detail || fallback);
  }
  return res;
}

export const phraseKey = (text: string) => text.trim().replace(/\s+/g, ' ').toLowerCase();

// 저장했거나 저장돼 있다고 확인한 구. 저장 안 됨은 다른 화면에서 저장됐을 수 있어 담지 않는다.
const savedPhrases = new Set<string>();
// 이 세션에서 저장한 낱말(낱말에는 저장 여부를 묻는 주소가 없다).
const savedWords = new Set<string>();
const listeners = new Set<(key: string) => void>();

// 같은 항목의 별과 저장 버튼이 서로 저장된 것을 알게 하는 알림 통로. 키는 savedKey로 만든다.
export const savedKey = (kind: 'word' | 'phrase', text: string) => (kind === 'word' ? `w:${text.toLowerCase()}` : `p:${phraseKey(text)}`);
export function onSaved(listener: (key: string) => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
export const isWordSaved = (lemma: string) => savedWords.has(lemma.toLowerCase());
export function markWordSaved(lemma: string): void {
  savedWords.add(lemma.toLowerCase());
  listeners.forEach((l) => l(savedKey('word', lemma)));
}

// extra.sentence: 표현을 만난 문장. extra.source: 클립에서 저장했다면 그 영상과 시각.
export async function savePhrase(text: string, translation: string, extra: { sentence?: string; source?: SaveSource } = {}): Promise<void> {
  await postPhrase('/api/phrase/save', { text, translation, ...extra }, '카드로 저장하지 못했어요.');
  savedPhrases.add(phraseKey(text));
  listeners.forEach((l) => l(savedKey('phrase', text)));
}

export async function phraseStatus(texts: string[]): Promise<boolean[]> {
  if (!texts.length) return [];
  const res = await postPhrase('/api/phrase/status', { texts }, '저장 여부를 확인하지 못했어요.');
  const data = await res.json();
  const saved: unknown[] = Array.isArray(data?.saved) ? data.saved : [];
  return texts.map((_, i) => saved[i] === true);
}

type Pending = { text: string; resolve: (saved: boolean) => void; reject: (e: unknown) => void };
let pending: Pending[] = [];

// 같은 틱에 모인 확인 요청을 한 번의 /api/phrase/status로 묶는다(별이 여러 개인 화면에서 요청을 줄인다).
export function isPhraseSaved(text: string): Promise<boolean> {
  if (savedPhrases.has(phraseKey(text))) return Promise.resolve(true);
  return new Promise((resolve, reject) => {
    if (!pending.length) setTimeout(flushStatus, 0);
    pending.push({ text, resolve, reject });
  });
}

function flushStatus() {
  const batch = pending;
  pending = [];
  const texts = [...new Set(batch.map((p) => phraseKey(p.text)))].slice(0, 40);
  phraseStatus(texts).then(
    (flags) => {
      texts.forEach((t, i) => flags[i] && savedPhrases.add(t));
      batch.forEach((p) => p.resolve(savedPhrases.has(phraseKey(p.text))));
    },
    (e: unknown) => batch.forEach((p) => p.reject(e)),
  );
}

const glossCache = new Map<string, string>();

// 구의 짧은 한국어 뜻. 서버나 모델이 실패하면 빈 문자열을 돌려주고, 화면은 뜻 없이도 저장하게 둔다.
export async function glossPhrase(text: string, signal?: AbortSignal): Promise<string> {
  const key = phraseKey(text);
  const hit = glossCache.get(key);
  if (hit !== undefined) return hit;
  try {
    const res = await fetch('/api/phrase/gloss', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.trim().replace(/\s+/g, ' ') }),
      signal,
    });
    if (!res.ok) return '';
    const data = await res.json();
    const gloss = typeof data?.gloss === 'string' ? data.gloss : '';
    if (gloss) glossCache.set(key, gloss);
    return gloss;
  } catch {
    return '';
  }
}
