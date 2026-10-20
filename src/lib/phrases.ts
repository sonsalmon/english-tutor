import { ReadglossOffError } from './api';

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

export async function savePhrase(text: string, translation: string): Promise<void> {
  await postPhrase('/api/phrase/save', { text, translation }, '카드로 저장하지 못했어요.');
}

export async function phraseStatus(texts: string[]): Promise<boolean[]> {
  if (!texts.length) return [];
  const res = await postPhrase('/api/phrase/status', { texts }, '저장 여부를 확인하지 못했어요.');
  const data = await res.json();
  const saved: unknown[] = Array.isArray(data?.saved) ? data.saved : [];
  return texts.map((_, i) => saved[i] === true);
}
