import { useEffect, useState } from 'react';

export type Route = 'home' | 'missions' | 'topic' | 'teachback' | 'call' | 'summary';
const ROUTES: Route[] = ['home', 'missions', 'topic', 'teachback', 'call', 'summary'];

function parse(hash: string): Route {
  const name = hash.replace(/^#\/?/, '') as Route;
  return ROUTES.includes(name) ? name : 'home';
}

export function go(route: Route, replace = false) {
  const hash = route === 'home' ? '#/' : `#/${route}`;
  if (replace) window.location.replace(hash);
  else window.location.hash = hash;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
