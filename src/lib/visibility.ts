import { PARTNERS, isPark, type Partner } from './partners';

// 화면에서만 숨기는 친구. 서버의 기억, 채팅 파일, 설정은 그대로 둔다.
export const HIDDEN_PARTNER_IDS: readonly string[] = ['omar', 'lukas', 'carmen', 'chloe'];

const SHOW_ALL_KEY = 'english-tutor.show-all-friends';

export function loadShowAllFriends(): boolean {
  try {
    return window.localStorage.getItem(SHOW_ALL_KEY) === '1';
  } catch {
    return false;
  }
}

export function saveShowAllFriends(value: boolean): void {
  try {
    if (value) window.localStorage.setItem(SHOW_ALL_KEY, '1');
    else window.localStorage.removeItem(SHOW_ALL_KEY);
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 화면에서만 바뀐다.
  }
}

// Ms. Park(코치)은 언제나 보인다. 친구는 숨김 목록을 뺀 나머지이고, showAll이면 전부 보인다.
export function visiblePartners(showAll: boolean = loadShowAllFriends(), partners: Partner[] = PARTNERS): Partner[] {
  return partners.filter((p) => isPark(p) || showAll || !HIDDEN_PARTNER_IDS.includes(p.id));
}

export function visibleFriends(showAll: boolean = loadShowAllFriends(), partners: Partner[] = PARTNERS): Partner[] {
  return visiblePartners(showAll, partners).filter((p) => !isPark(p));
}
