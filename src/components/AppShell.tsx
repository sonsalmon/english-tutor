import type { ReactNode } from 'react';
import { NAV_ITEMS } from '../lib/nav';
import { go, type Route } from '../lib/router';
import { Portrait } from './ui';

// 통화 화면은 사이드바 없이 전체를 쓴다. 통화 중에 다른 메뉴로 나가면 통화가 끊기기 때문이다.
export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  if (route === 'call') return <>{children}</>;
  return (
    <div className="lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-60 flex-col border-r border-line bg-surface px-3 py-6 lg:flex">
        <div className="flex items-center gap-3 px-2">
          <Portrait size={48} />
          <div className="min-w-0">
            <p className="font-bold leading-tight">English Tutor</p>
            <p className="text-sm text-ink-soft">Ms. Park</p>
          </div>
        </div>
        <nav aria-label="주 메뉴" className="mt-8">
          <ul className="space-y-1">
            {NAV_ITEMS.map(({ label, route: target, icon: Icon }) => {
              const active = target === route;
              return (
                <li key={target}>
                  <button
                    type="button"
                    onClick={() => go(target)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left font-semibold ${
                      active ? 'bg-ink text-white' : 'text-ink hover:bg-paper'
                    }`}
                  >
                    <Icon size={20} aria-hidden />
                    {label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
      {children}
    </div>
  );
}
