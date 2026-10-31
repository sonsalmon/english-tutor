import { History as HistoryIcon, Mic } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ScreenSettings } from '../components/ScreenSettings';
import { List, QuietButton, RowLink, Screen } from '../components/ui';
import { ABOUT_ME_MAX, DEFAULT_MEMORY_SETTINGS, getMemorySettings, putMemorySettings, type MemoryRemember } from '../lib/apiMemorySettings';
import { loadCorrection, loadFriendCoach, saveCorrection, saveFriendCoach, type CorrectionStrength } from '../lib/coachSettings';
import { loadCallEngine, saveCallEngine, VISIBLE_CALL_ENGINES, type CallEngine } from '../lib/engineSettings';
import { friendlyError } from '../lib/errors';
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

const CORRECTION_OPTIONS: { value: CorrectionStrength; label: string; desc: string }[] = [
  { value: 'off', label: '고치지 않기', desc: '틀려도 말하지 않고 잘한 점만 말해요.' },
  { value: 'light', label: '약하게', desc: '분명한 실수만 말이 끝날 때 짧게 알려 줘요.' },
  { value: 'normal', label: '보통', desc: '말하는 중에 바른 말로 자연스럽게 다시 말해 주고, 끝에 고칠 점을 알려 줘요.' },
];

function CorrectionSettings() {
  const [strength, setStrength] = useState<CorrectionStrength>(() => loadCorrection());
  const choose = (value: CorrectionStrength) => {
    setStrength(value);
    saveCorrection(value);
  };
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 font-bold">Ms. Park이 고쳐 주는 정도</legend>
      <div className="space-y-2">
        {CORRECTION_OPTIONS.map((o) => (
          <label key={o.value} className="relative block">
            <input type="radio" name="correction-strength" value={o.value} checked={strength === o.value} onChange={() => choose(o.value)} className="peer sr-only" />
            <span className="block min-h-14 cursor-pointer rounded-2xl border border-line bg-surface px-4 py-3 peer-checked:border-ink peer-checked:ring-1 peer-checked:ring-ink peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink/45">
              <span className="block font-semibold">{o.label}</span>
              <span className="mt-0.5 block text-sm text-ink-soft">{o.desc}</span>
            </span>
          </label>
        ))}
      </div>
      <p className="mt-3 text-sm text-ink-soft">다음 통화부터 적용돼요.</p>
    </fieldset>
  );
}

// 모든 엔진의 문구를 두되, 화면에는 VISIBLE_CALL_ENGINES에 든 것만 보인다.
const ENGINE_TEXT: Record<CallEngine, { label: string; desc: string }> = {
  gemini_live: { label: 'Gemini 2.5 Live', desc: '예전 기본 모델이에요.' },
  gemini_live_38: { label: '기본: Gemini 3.8 Live', desc: "말을 끊으면 바로 멈추고, 'Yeah'에도 자기 이야기를 이어가요." },
  gemini_live_notes: { label: '조용한 조언자', desc: '말하는 동안 곁에서 조용히 메모하며 대화를 거들어요.' },
  cascade_flux: { label: '조립식', desc: 'Deepgram이 듣고, Gemini가 생각하고, Cartesia가 말해요.' },
  openai_live: { label: 'OpenAI 실시간', desc: '아직 만들고 있어요.' },
};
const ENGINE_OPTIONS = VISIBLE_CALL_ENGINES.map((value) => ({ value, ...ENGINE_TEXT[value] }));

function EngineSettings() {
  const [engine, setEngine] = useState<CallEngine>(() => loadCallEngine());
  const choose = (value: CallEngine) => {
    setEngine(value);
    saveCallEngine(value);
  };
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 font-bold">실험실: 통화 엔진</legend>
      <div className="space-y-2">
        {ENGINE_OPTIONS.map((o) => (
          <label key={o.value} className="relative block">
            <input type="radio" name="call-engine" value={o.value} checked={engine === o.value} onChange={() => choose(o.value)} className="peer sr-only" />
            <span className="block min-h-14 cursor-pointer rounded-2xl border border-line bg-surface px-4 py-3 peer-checked:border-ink peer-checked:ring-1 peer-checked:ring-ink peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink/45">
              <span className="block font-semibold">{o.label}</span>
              <span className="mt-0.5 block text-sm text-ink-soft">{o.desc}</span>
            </span>
          </label>
        ))}
      </div>
      <p className="mt-3 text-sm text-ink-soft">친구 수다 통화에만 적용. 다음 통화부터 바뀌어요.</p>
    </fieldset>
  );
}

type SaveState = { status: 'idle' | 'saving' | 'saved' | 'error'; message?: string };

function MemorySettingsSection() {
  const [load, setLoad] = useState<'loading' | 'ready' | 'error'>('loading');
  const [reloadKey, setReloadKey] = useState(0);
  const [aboutMe, setAboutMe] = useState(DEFAULT_MEMORY_SETTINGS.about_me);
  const [remember, setRemember] = useState<MemoryRemember>(DEFAULT_MEMORY_SETTINGS.remember);
  const [save, setSave] = useState<SaveState>({ status: 'idle' });

  useEffect(() => {
    setLoad('loading');
    const controller = new AbortController();
    getMemorySettings(controller.signal).then(
      (settings) => {
        setAboutMe(settings.about_me);
        setRemember(settings.remember);
        setLoad('ready');
      },
      () => {
        if (!controller.signal.aborted) setLoad('error');
      },
    );
    return () => controller.abort();
  }, [reloadKey]);

  const changeAboutMe = (value: string) => {
    setAboutMe(value);
    setSave({ status: 'idle' });
  };
  const changeSwitch = (key: keyof MemoryRemember, value: boolean) => {
    setRemember((prev) => ({ ...prev, [key]: value }));
    setSave({ status: 'idle' });
  };
  const submit = async () => {
    setSave({ status: 'saving' });
    try {
      const saved = await putMemorySettings({ about_me: aboutMe, remember });
      setAboutMe(saved.about_me);
      setRemember(saved.remember);
      setSave({ status: 'saved' });
    } catch (e) {
      setSave({ status: 'error', message: friendlyError(e, '저장하지 못했어요.') });
    }
  };

  return (
    <section>
      <h2 className="mb-2 font-bold">나에 대한 기억</h2>
      {load === 'loading' && <p className="text-sm text-ink-soft">불러오는 중이에요…</p>}
      {load === 'error' && (
        <div className="space-y-2">
          <p role="alert" className="text-sm text-end">설정을 불러오지 못했어요.</p>
          <QuietButton onClick={() => setReloadKey((k) => k + 1)}>다시 불러오기</QuietButton>
        </div>
      )}
      {load === 'ready' && (
        <div className="space-y-3">
          <div>
            <label htmlFor="about-me" className="block font-semibold">친구들이 알고 있었으면 하는 나에 대한 것</label>
            <textarea
              id="about-me"
              value={aboutMe}
              maxLength={ABOUT_ME_MAX}
              onChange={(e) => changeAboutMe(e.target.value)}
              placeholder="예: 나는 IT 회사에서 일하고, 주말에는 바둑을 둬요. 요즘 영어 면접을 준비하고 있어요."
              className="mt-2 min-h-32 w-full rounded-2xl border border-line bg-surface px-4 py-3 text-base"
            />
            <p className="mt-1 text-right text-sm text-ink-soft">{aboutMe.length}/{ABOUT_ME_MAX}</p>
          </div>
          <ToggleRow label="내가 말한 사실 기억하기" desc="대화에서 내가 말한 내 이야기, 친구가 정리한 인상, 지난 대화 요약을 기억해요." checked={remember.facts} onChange={(v) => changeSwitch('facts', v)} />
          <ToggleRow label="지난 화제 이어 가기" desc="지난 대화에서 남긴 이어 갈 이야기를 다음 대화에서 먼저 꺼내요." checked={remember.threads} onChange={(v) => changeSwitch('threads', v)} />
          <ToggleRow label="관심사 기억하기" desc="통화에서 알게 된 내 관심사를 학습자 카드에 쌓고 친구가 대화에 써요." checked={remember.interests} onChange={(v) => changeSwitch('interests', v)} />
          <p className="text-sm text-ink-soft">스위치를 꺼도 이미 저장된 기억은 지워지지 않아요. 꺼 둔 동안에는 새로 쌓지도, 대화에 꺼내지도 않아요. 다음 대화부터 적용돼요.</p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={save.status === 'saving'}
              className="min-h-12 rounded-full bg-ink px-6 font-semibold text-white disabled:opacity-50"
            >
              {save.status === 'saving' ? '저장 중…' : '저장'}
            </button>
            {save.status === 'saved' && <span role="status" className="text-sm text-ink-soft">저장했어요.</span>}
            {save.status === 'error' && <span role="alert" className="text-sm text-end">{save.message}</span>}
          </div>
        </div>
      )}
    </section>
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
  const [friendCoach, setFriendCoach] = useState(() => loadFriendCoach());
  const changeFriendCoach = (value: boolean) => {
    setFriendCoach(value);
    saveFriendCoach(value);
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
        <CorrectionSettings />
        <ToggleRow
          label="친구가 코치도 해 주기"
          desc={'내가 "Was that right?"처럼 묻거나 같은 실수를 되풀이하면, 친구가 짧게 한마디 알려 주고 바로 친구로 돌아와요. 알려 주는 정도는 위 설정을 따라요. 끄면 친구는 영어를 고치지 않아요.'}
          checked={friendCoach}
          onChange={changeFriendCoach}
        />
        <MemorySettingsSection />
        <EngineSettings />
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
