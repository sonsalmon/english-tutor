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
