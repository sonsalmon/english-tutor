import { useEffect, useState } from 'react';

export type Route = 'home' | 'smalltalk' | 'missions' | 'topic' | 'teachback' | 'pron' | 'call' | 'summary' | 'history' | 'replay' | 'chat';
const ROUTES: Route[] = ['home', 'smalltalk', 'missions', 'topic', 'teachback', 'pron', 'call', 'summary', 'history', 'replay', 'chat'];

function segments(hash: string): string[] {
  return hash.replace(/^#\/?/, '').split('/');
}

function parse(hash: string): Route {
  const name = segments(hash)[0] as Route;
  return ROUTES.includes(name) ? name : 'home';
}

// #/history/<stem>처럼 경로 뒤에 붙은 값. 없으면 null.
function parseParam(hash: string): string | null {
  return segments(hash)[1] || null;
}

export function go(route: Route, replace = false, param?: string) {
  const path = route === 'home' ? '' : route + (param ? `/${encodeURIComponent(param)}` : '');
  const hash = `#/${path}`;
  if (replace) window.location.replace(hash);
  else window.location.hash = hash;
}

function useHash<T>(read: (hash: string) => T): T {
  const [value, setValue] = useState<T>(() => read(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setValue(read(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [read]);
  return value;
}

export function useRoute(): Route {
  return useHash(parse);
}

export function useRouteParam(): string | null {
  const raw = useHash(parseParam);
  if (raw === null) return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
