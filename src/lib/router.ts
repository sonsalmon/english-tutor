import { useSyncExternalStore } from 'react';

// 'smalltalk'과 'history'는 옛 주소다. App이 새 주소로 replace한다(즐겨찾기와 서비스 워커 캐시에 남아 있어서 지우지 않는다).
export type Route =
  | 'home'
  | 'person'
  | 'log'
  | 'words'
  | 'feed'
  | 'settings'
  | 'smalltalk'
  | 'missions'
  | 'topic'
  | 'teachback'
  | 'pron'
  | 'call'
  | 'summary'
  | 'history'
  | 'replay'
  | 'chat'
  | 'clip';
const ROUTES: Route[] = [
  'home',
  'person',
  'log',
  'words',
  'feed',
  'settings',
  'smalltalk',
  'missions',
  'topic',
  'teachback',
  'pron',
  'call',
  'summary',
  'history',
  'replay',
  'chat',
  'clip',
];

function segments(hash: string): string[] {
  return hash.replace(/^#\/?/, '').split('/');
}

function parse(hash: string): Route {
  const name = segments(hash)[0] as Route;
  return ROUTES.includes(name) ? name : 'home';
}

// #/log/<stem>처럼 경로 뒤에 붙은 값. 없으면 null.
function parseParam(hash: string): string | null {
  return segments(hash)[1] || null;
}

export function go(route: Route, replace = false, param?: string) {
  const path = route === 'home' ? '' : route + (param ? `/${encodeURIComponent(param)}` : '');
  const hash = `#/${path}`;
  if (replace) window.location.replace(hash);
  else window.location.hash = hash;
}

// route와 param이 같은 해시를 한 번에 읽도록 외부 저장소로 구독한다. 따로 상태를 두면 해시가 바뀐 직후
// route만 새 값인 어긋난 렌더가 생겨서, param이 필요한 화면이 잘못 홈으로 되돌린다.
function subscribe(notify: () => void) {
  const onChange = () => {
    window.scrollTo(0, 0);
    notify();
  };
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
}

function currentHash(): string {
  return window.location.hash;
}

export function useRoute(): Route {
  return parse(useSyncExternalStore(subscribe, currentHash));
}

export function useRouteParam(): string | null {
  const raw = parseParam(useSyncExternalStore(subscribe, currentHash));
  if (raw === null) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
