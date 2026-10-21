import type { LearnerProfile, Wordbook } from './api';

// 친구에게 내 단어장(단어와 저장한 문장)을 보여 줄지. 기본은 켬.
const KEY = 'english-tutor.share-wordbook';

export function loadShareWordbook(): boolean {
  try {
    return localStorage.getItem(KEY) !== '0';
  } catch {
    return true;
  }
}

export function saveShareWordbook(value: boolean): void {
  try {
    localStorage.setItem(KEY, value ? '1' : '0');
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 방문에만 적용된다.
  }
}

// 친구에게 줄 단어장. 단어장 공유 설정이 꺼져 있어도 원어민 표현(내 데이터가 아니다)은 그대로 담는다.
export function friendWordbook(profile: LearnerProfile | null): Wordbook | null {
  const book = loadShareWordbook() ? profile?.wordbook ?? null : null;
  const native = profile?.native_expressions ?? [];
  if (!native.length) return book;
  return { words: book?.words ?? [], phrases: book?.phrases ?? [], native };
}
