import { History as HistoryIcon, Mic } from 'lucide-react';
import { useState } from 'react';
import { ScreenSettings } from '../components/ScreenSettings';
import { List, RowLink, Screen } from '../components/ui';
import { loadKoSettings, saveKoSettings } from '../lib/koLines';
import { go } from '../lib/router';
import { loadShareWordbook, saveShareWordbook } from '../lib/shareWordbook';
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
  const [shareBook, setShareBook] = useState(() => loadShareWordbook());
  const changeShareBook = (value: boolean) => {
    setShareBook(value);
    saveShareWordbook(value);
  };
  const [koEnabled, setKoEnabled] = useState(() => loadKoSettings().enabled);
  const changeKoEnabled = (value: boolean) => {
    setKoEnabled(value);
    saveKoSettings({ ...loadKoSettings(), enabled: value });
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
          label="친구에게 내 단어장 보여주기"
          desc="친구가 내 단어장의 단어와 저장한 문장을 알고 대화에 가끔 써요. 단어와 짧은 문장만 가고, 읽던 글과 주소는 가지 않아요."
          checked={shareBook}
          onChange={changeShareBook}
        />
        <ToggleRow
          label="클립 공부의 한국어 줄"
          desc="클립 공부 화면에서 보는 줄만 한국어로 번역해요. 하루 300줄까지만 쓰고, 한 번 받은 줄은 다시 부르지 않아요. 끄면 번역을 한 번도 요청하지 않아요."
          checked={koEnabled}
          onChange={changeKoEnabled}
        />
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
