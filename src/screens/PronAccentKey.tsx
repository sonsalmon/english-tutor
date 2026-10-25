import { useCallback, useEffect, useState } from 'react';
import { QuietButton } from '../components/ui';
import { getAccentKey, removeAccentEntry, type AccentAction, type AccentHabit, type AccentKey, type AccentWord } from '../lib/api';

const ACTION_LABEL: Record<AccentAction, string> = { practice: '연습할 발음', adjust: '앱이 알아서 보정' };

function ActionBadge({ action }: { action: AccentAction }) {
  const style = action === 'practice' ? 'bg-marker text-ink' : 'border border-line bg-paper text-ink-soft';
  return <span className={`inline-flex shrink-0 items-center rounded-full px-3 py-1 text-sm font-semibold ${style}`}>{ACTION_LABEL[action]}</span>;
}

// 실수로 누르기 쉬우므로 한 번 더 확인한 뒤 지운다.
function RemoveButton({ what, onRemove }: { what: string; onRemove: () => Promise<void> }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const confirm = async () => {
    setBusy(true);
    setError('');
    try {
      await onRemove();
    } catch (e) {
      setError(e instanceof Error ? e.message : '지우지 못했어요.');
      setBusy(false);
    }
  };

  if (!asking) {
    return (
      <button type="button" onClick={() => setAsking(true)} aria-label={`${what} 지우기`} className="-ml-3 min-h-11 rounded-xl px-3 text-sm font-semibold text-ink-soft underline decoration-line underline-offset-4 active:text-ink">
        틀렸어요, 지우기
      </button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`${what} 지울까요?`}>
      <span className="text-sm">정답지에서 지울까요?</span>
      <button type="button" disabled={busy} onClick={() => void confirm()} className="min-h-11 rounded-xl bg-end px-4 text-sm font-bold text-white active:bg-end-press disabled:opacity-50">
        지우기
      </button>
      <button type="button" disabled={busy} onClick={() => setAsking(false)} className="min-h-11 rounded-xl border border-line px-4 text-sm font-semibold active:bg-paper disabled:opacity-50">
        취소
      </button>
      {error && (
        <p role="alert" className="w-full text-sm text-end-press">
          {error}
        </p>
      )}
    </div>
  );
}

function HabitCard({ habit, onRemove }: { habit: AccentHabit; onRemove: () => Promise<void> }) {
  const examples = habit.examples.slice(0, 2);
  return (
    <article className="rounded-2xl border border-line bg-surface p-5">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-bold" lang="en">
            {habit.meant} <span className="text-ink-soft">→</span> {habit.heard_as}
          </h3>
          <p className="mt-0.5 text-sm text-ink-soft">
            <span lang="en">{habit.label}</span> 소리 · {habit.total}문장 중 {habit.count}문장에서 이렇게 들렸어요
          </p>
        </div>
        <ActionBadge action={habit.action} />
      </header>
      {examples.length > 0 && (
        <ul className="mt-3 space-y-2">
          {examples.map((e, i) => (
            <li key={i} className="rounded-xl bg-paper px-3 py-2 text-[15px] leading-relaxed">
              {e.meant_text && (
                <>
                  <span className="text-ink-soft">읽은 문장 </span>
                  <span lang="en" className="font-semibold">
                    {e.meant_text}
                  </span>
                </>
              )}
              <span className="block text-ink-soft">
                이렇게 들렸어요 <span lang="en" className="text-ink">{e.heard_text}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {habit.tip && habit.action === 'practice' && (
        <details className="mt-3 rounded-xl border border-line px-3 py-2">
          <summary className="min-h-8 cursor-pointer text-sm font-semibold">고치는 방법</summary>
          <p className="mt-1 text-[15px] leading-relaxed">{habit.tip}</p>
        </details>
      )}
      <div className="mt-2">
        <RemoveButton what={`${habit.meant}가 ${habit.heard_as}로 들리는 습관`} onRemove={onRemove} />
      </div>
    </article>
  );
}

function WordRow({ word, onRemove }: { word: AccentWord; onRemove: () => Promise<void> }) {
  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold" lang="en">
            {word.intended} <span className="text-ink-soft">→</span> {word.heard}
          </p>
          <p className="text-sm text-ink-soft">
            통화 {word.count}번에서 이렇게 들렸어요{word.last_seen ? ` · 마지막 ${word.last_seen.slice(0, 10)}` : ''}
          </p>
        </div>
        <ActionBadge action={word.action} />
      </div>
      <div>
        <RemoveButton what={`${word.intended}가 ${word.heard}로 들린 단어`} onRemove={onRemove} />
      </div>
    </li>
  );
}

export function AccentKeySection() {
  const [key, setKey] = useState<AccentKey | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    const controller = new AbortController();
    setError('');
    getAccentKey(controller.signal).then(setKey, (e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '말투 정답지를 불러오지 못했어요.');
    });
    return () => controller.abort();
  }, []);

  useEffect(() => load(), [load]);

  const remove = (kind: 'habit' | 'word', id: string) => async () => setKey(await removeAccentEntry(kind, id));

  return (
    <section className="mt-8" aria-labelledby="accent-key-title">
      <h2 id="accent-key-title" className="text-lg font-bold">
        내 말투 정답지
      </h2>
      <p className="mt-1 max-w-[640px] leading-relaxed text-ink-soft">
        내 말투 때문에 다르게 들리는 소리예요. 통화 상대는 이 표를 보고, 되묻지 않고 내가 하려던 말로 알아들어요. 두 뜻이 다 말이 될 때만 한 번 물어봐요.
      </p>
      <ul className="mt-3 max-w-[640px] space-y-1 text-sm leading-relaxed">
        <li>
          <b>연습할 발음</b>: 자주 다르게 들려서 연습하면 좋아요.
        </li>
        <li>
          <b>앱이 알아서 보정</b>: 가끔만 달라서 연습하지 않아도 돼요. 앱이 알아서 맞춰 들어요.
        </li>
      </ul>

      {error && (
        <div role="alert" className="mt-4">
          <p className="text-end-press">{error}</p>
          <div className="mt-3">
            <QuietButton onClick={load}>다시 불러오기</QuietButton>
          </div>
        </div>
      )}
      {!key && !error && <p className="mt-4 text-ink-soft">불러오는 중이에요.</p>}

      {key && key.habits.length === 0 && key.words.length === 0 && (
        <p className="mt-4 rounded-2xl border border-line bg-surface p-5">아직 정답지가 비어 있어요. 발음 진단을 하면 여기에 채워져요.</p>
      )}

      {key && key.habits.length > 0 && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2 lg:items-start">
          {key.habits.map((h) => (
            <HabitCard key={h.id} habit={h} onRemove={remove('habit', h.id)} />
          ))}
        </div>
      )}

      {key && key.words.length > 0 && (
        <div className="mt-6">
          <h3 className="mb-2 font-semibold">통화에서 찾은 단어</h3>
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface lg:max-w-[640px]">
            {key.words.map((w) => (
              <WordRow key={w.id} word={w} onRemove={remove('word', w.id)} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
