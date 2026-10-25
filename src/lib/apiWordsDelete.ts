import { ReadglossOffError } from './api';

export type WordbookKind = 'word' | 'phrase';
// 서버가 지우기 전 내용을 돌려준 그대로다. 되돌리기에 통째로 다시 보낸다.
export type WordbookSnapshot = Record<string, unknown>;

async function detailOf(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string' && body.detail) return body.detail;
  } catch {
    // 본문이 없으면 기본 문구
  }
  return fallback;
}

async function send(url: string, init: RequestInit, fallback: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (res.status === 503) throw new ReadglossOffError(await detailOf(res, fallback));
  if (!res.ok) throw new Error(await detailOf(res, fallback));
  return res;
}

// 저장소(readgloss)에서 지운다. 지운 내용을 돌려받아 되돌리기에 쓴다.
export async function deleteWordbookItem(kind: WordbookKind, key: string): Promise<WordbookSnapshot> {
  const res = await send(`/api/wordbook/${kind}/${encodeURIComponent(key)}`, { method: 'DELETE' }, '지우지 못했어요.');
  const data = await res.json();
  return (data?.snapshot ?? {}) as WordbookSnapshot;
}

export async function restoreWordbookItem(snapshot: WordbookSnapshot): Promise<void> {
  await send(
    '/api/wordbook/restore',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ snapshot }) },
    '되돌리지 못했어요.',
  );
}
