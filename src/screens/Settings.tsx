import { History as HistoryIcon, Mic } from 'lucide-react';
import { useState } from 'react';
import { ScreenSettings } from '../components/ScreenSettings';
import { List, RowLink, Screen } from '../components/ui';
import { go } from '../lib/router';
import { loadShowAllFriends, saveShowAllFriends } from '../lib/visibility';

function ToggleRow({ label, desc, checked, onChange }: { label: string; desc: string; checked: boolean; onChange: (value: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex min-h-14 w-full items-center gap-4 rounded-2xl border border-line bg-surface px-4 py-3 text-left hover:bg-paper"
    >
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{label}</span>
        <span className="mt-0.5 block text-sm text-ink-soft">{desc}</span>
      </span>
      <span aria-hidden className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${checked ? 'bg-call' : 'bg-ink-soft/40'}`}>
        <span className={`absolute top-0.5 left-0.5 size-6 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </span>
    </button>
  );
}

export function Settings() {
  const [showAll, setShowAll] = useState(() => loadShowAllFriends());
  const changeShowAll = (value: boolean) => {
    setShowAll(value);
    saveShowAllFriends(value);
  };
  return (
    <Screen>
      <header className="flex h-11 items-center lg:mb-4 lg:h-auto">
        <h1 className="text-[28px] font-bold">설정</h1>
      </header>
      <div className="mt-4 space-y-8">
        <ScreenSettings />
        <section>
          <h2 className="mb-2 font-bold">그 밖의 설정</h2>
          <List>
            <RowLink icon={Mic} title="발음 진단" desc="문장을 읽고 어떻게 들리는지 확인해요" onClick={() => go('pron')} />
            <RowLink icon={HistoryIcon} title="전체 통화 기록" desc="모든 사람과의 통화를 모아 봐요" onClick={() => go('log')} />
          </List>
        </section>
        <ToggleRow
          label="숨긴 친구 보기"
          desc="목록에서 숨긴 친구 네 명(Omar, Lukas, Carmen, Chloe)도 보여요. 이야기한 기억은 그대로 남아 있어요."
          checked={showAll}
          onChange={changeShowAll}
        />
      </div>
    </Screen>
  );
}
