import { useEffect, useState, type ReactNode } from 'react';
import { getPeople, orderPeople, previewOf, type PersonActivity } from '../lib/apiPeople';
import { listTime } from '../lib/callFormat';
import { isPark } from '../lib/partners';
import { go } from '../lib/router';
import { visiblePartners } from '../lib/visibility';
import { Avatar } from './Avatar';
import { List } from './ui';

// 데스크톱의 두 칸: 왼쪽 사람 목록 320px, 오른쪽은 고른 사람이나 통화 내역 상세.
export function TwoPane({ list, children }: { list: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[320px_minmax(0,1fr)] items-start gap-10">
      <div>{list}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

function usePeopleActivity(): PersonActivity[] {
  const [activity, setActivity] = useState<PersonActivity[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    getPeople(controller.signal).then(setActivity, () => {});
    return () => controller.abort();
  }, []);
  return activity;
}

// 메신저처럼 사람이 떠 있는 목록. Ms. Park은 맨 위에 고정하고 친구는 마지막 활동 순서다.
export function PeopleList({ activeId, parkHint }: { activeId: string | null; parkHint?: string }) {
  const activity = usePeopleActivity();
  const people = orderPeople(visiblePartners(), activity);
  const byId = new Map(activity.map((a) => [a.id, a]));
  return (
    <nav aria-label="사람 목록">
      <List>
        {people.map((p) => {
          const park = isPark(p);
          const found = byId.get(p.id);
          const preview = previewOf(found);
          const text = park && parkHint ? `오늘 연습: ${parkHint}` : preview ? preview.text : p.intro;
          const lang = !park && preview?.kind === 'message' ? 'en' : undefined;
          const active = p.id === activeId;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => go('person', false, p.id)}
              aria-current={active ? 'true' : undefined}
              data-person={p.id}
              className={`flex min-h-[72px] w-full items-center gap-4 px-4 py-3 text-left hover:bg-paper ${active ? 'bg-paper' : ''}`}
            >
              <Avatar partner={p} size={56} />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-bold">{p.name}</span>
                    {park && <span className="shrink-0 rounded-full bg-line px-2 py-0.5 text-xs font-semibold text-ink">코치</span>}
                  </span>
                  <span className="shrink-0 text-xs text-ink-soft">{listTime(found?.last_at)}</span>
                </span>
                <span lang={lang} className="mt-0.5 block truncate text-sm text-ink-soft">
                  {text}
                </span>
              </span>
            </button>
          );
        })}
      </List>
    </nav>
  );
}
