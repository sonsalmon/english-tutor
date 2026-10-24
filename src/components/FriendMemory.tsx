import { useEffect, useRef, useState } from 'react';
import { clearPartnerMemory, forgetPartnerMemoryItem, getPartnerMemory, MemoryChangedError, type PartnerMemory, type PartnerMemoryKind } from '../lib/api';

export type MemoryState = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; memory: PartnerMemory | null };

// 한국어 발음 기준 조사: 카르멘과 브라이언은 받침이 있어 '이', 나머지는 '가'.
function subject(id: string): string {
  return id === 'carmen' || id === 'brian' ? '이' : '가';
}

function ForgetButton({ label, onClick, disabled, focusKey }: { label: string; onClick: () => void; disabled: boolean; focusKey: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-forget={focusKey}
      aria-label={`${label} 지우기`}
      className="-my-1 min-h-11 shrink-0 rounded-full px-3 text-sm font-semibold text-ink-soft hover:bg-paper hover:text-ink disabled:opacity-50"
    >
      지우기
    </button>
  );
}

// 고른 친구가 기억하는 것. 한 줄씩 지우거나 모두 지울 수 있다.
export function FriendMemory({ partnerId, name, state, onChange }: {
  partnerId: string;
  name: string;
  state: MemoryState;
  onChange: (memory: PartnerMemory | null) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [notice, setNotice] = useState('');
  const rootRef = useRef<HTMLElement | null>(null);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  // 지운 뒤 포커스를 보낼 곳. 다음 줄의 지우기 버튼이거나(키), 없으면 제목이다.
  const pendingFocus = useRef<string | null>(null);
  const memory = state.status === 'ready' ? state.memory : null;
  const empty = !memory || (memory.facts.length === 0 && memory.threads.length === 0 && memory.self_story.length === 0 && memory.jokes.length === 0 && memory.episodes.length === 0);
  const failed = state.status === 'failed';

  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    const next = key === 'heading' ? null : rootRef.current?.querySelector<HTMLElement>(`[data-forget="${key}"]`);
    (next ?? headingRef.current)?.focus();
  }, [state]);

  const forget = async (kind: PartnerMemoryKind, index: number, text: string) => {
    setBusy(true);
    setProblem('');
    setNotice('');
    setConfirming(false);
    try {
      const next = await forgetPartnerMemoryItem(partnerId, kind, index, text);
      pendingFocus.current = `${kind}-${index}`;
      onChange(next);
    } catch (e) {
      if (e instanceof MemoryChangedError) {
        // 화면이 보던 목록과 서버 목록이 달라졌다. 아무것도 지우지 않고 새로 불러온다.
        try {
          const fresh = await getPartnerMemory(partnerId);
          pendingFocus.current = 'heading';
          onChange(fresh);
          setNotice('기억이 바뀌어서 다시 불러왔어요.');
        } catch (e2) {
          setProblem(e2 instanceof Error ? e2.message : '기억을 다시 불러오지 못했어요.');
        }
      } else {
        setProblem(e instanceof Error ? e.message : '기억을 지우지 못했어요.');
      }
    } finally {
      setBusy(false);
    }
  };

  // 기억을 불러오지 못한 상태에서도 쓸 수 있는 초기화. 서버가 먼저 백업한 뒤 파일을 지운다.
  const clearAll = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    setProblem('');
    setNotice('');
    try {
      await clearPartnerMemory(partnerId);
      const fresh = await getPartnerMemory(partnerId).catch(() => null);
      setConfirming(false);
      pendingFocus.current = 'heading';
      onChange(fresh);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : '기억을 지우지 못했어요.');
    } finally {
      setBusy(false);
    }
  };

  const clearLabel = failed ? '기억 초기화' : '기억 모두 지우기';
  const confirmLabel = failed ? '정말 초기화할까요?' : '정말 지울까요?';

  return (
    <section ref={rootRef} aria-labelledby="friend-memory-title" className="mt-5 rounded-2xl border border-line bg-surface p-4 lg:mt-6 lg:p-5">
      <h2 id="friend-memory-title" ref={headingRef} tabIndex={-1} className="text-lg font-bold focus:outline-none">
        {name}
        {subject(partnerId)} 기억하는 것
      </h2>

      <div aria-live="polite">
        {state.status === 'loading' && <p className="mt-2 text-ink-soft">기억을 불러오는 중이에요.</p>}
        {failed && <p className="mt-2 text-ink-soft">지금은 기억을 볼 수 없어요. 통화는 그대로 할 수 있어요.</p>}
        {state.status === 'ready' && empty && (
          <p className="mt-2 text-ink-soft">
            아직 나눈 이야기가 없어요. 통화가 끝나면 {name}
            {subject(partnerId)} 기억해요.
          </p>
        )}
        {notice && <p className="mt-2 text-sm font-semibold text-ink">{notice}</p>}
        {confirming && <p className="sr-only">{confirmLabel} 한 번 더 누르면 지워져요.</p>}
      </div>

      {memory?.reflection?.text && (
        <div className="mt-3 rounded-xl bg-paper p-3">
          <h3 className="text-sm font-semibold text-ink-soft">
            {name}
            {subject(partnerId)} 나에 대해 아는 것 · {memory.reflection.date}
          </h3>
          <p lang="en" className="mt-1 text-[15px]">
            {memory.reflection.text}
          </p>
        </div>
      )}

      {memory && memory.threads.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">다음에 이어 갈 이야기</h3>
          <ul className="divide-y divide-line">
            {memory.threads.map((t, i) => (
              <li key={`${t.text}-${i}`} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{t.ko}</span>
                  <span lang="en" className="block text-sm text-ink-soft">
                    {t.text}
                  </span>
                </span>
                <ForgetButton label={t.ko} focusKey={`threads-${i}`} disabled={busy} onClick={() => void forget('threads', i, t.text)} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {memory && memory.facts.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">알게 된 것</h3>
          <ul className="divide-y divide-line">
            {memory.facts.map((f, i) => {
              const past = f.status === 'past';
              return (
                <li key={`${f.id ?? f.text}-${i}`} data-past={past ? 'true' : undefined} className={`flex items-center gap-2 py-2 ${past ? 'opacity-60' : ''}`}>
                  <span className="min-w-0 flex-1">
                    <span lang="en" className={`block text-[15px] ${past ? 'text-ink-soft' : ''}`}>
                      {f.text}
                    </span>
                    <span className="block text-xs text-ink-soft">
                      {past ? `지난 일${f.until ? ` · ${f.until}까지` : ''}` : `중요도 ${f.importance ?? 3}/5`} · {f.last_seen}
                    </span>
                  </span>
                  <ForgetButton label={f.text} focusKey={`facts-${i}`} disabled={busy} onClick={() => void forget('facts', i, f.text)} />
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {memory && memory.self_story.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">친구가 들려준 이야기</h3>
          <ul className="divide-y divide-line">
            {memory.self_story.map((s, i) => (
              <li key={`${s.story}-${i}`} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span lang="en" className="block font-semibold">
                    {s.story}
                  </span>
                  <span lang="en" className="block text-sm text-ink-soft">
                    {s.progress}
                  </span>
                </span>
                <ForgetButton label={s.story} focusKey={`self_story-${i}`} disabled={busy} onClick={() => void forget('self_story', i, s.progress)} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {memory && memory.jokes.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">같이 웃은 것</h3>
          <ul className="divide-y divide-line">
            {memory.jokes.map((j, i) => (
              <li key={`${j.text}-${i}`} className="flex items-center gap-2 py-2">
                <span lang="en" className="min-w-0 flex-1 text-[15px]">
                  {j.text}
                </span>
                <ForgetButton label={j.text} focusKey={`jokes-${i}`} disabled={busy} onClick={() => void forget('jokes', i, j.text)} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {memory && memory.episodes.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">지난 대화</h3>
          <ul className="divide-y divide-line">
            {memory.episodes.map((ep, i) => (
              <li key={`${ep.date}-${i}`} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-ink-soft">
                    {ep.date} · {ep.mode === 'chat' ? '채팅' : '통화'}
                  </span>
                  <span lang="en" className="block text-[15px]">
                    {ep.summary}
                  </span>
                </span>
                <ForgetButton label={`${ep.date} 대화`} focusKey={`episodes-${i}`} disabled={busy} onClick={() => void forget('episodes', i, ep.summary)} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {problem && (
        <p role="alert" className="mt-3 text-sm text-end-press">
          {problem}
        </p>
      )}

      {(!empty || failed) && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={() => void clearAll()}
            disabled={busy}
            className={`min-h-11 rounded-full border px-5 text-sm font-semibold disabled:opacity-50 ${confirming ? 'border-end bg-end text-white active:bg-end-press' : 'border-line bg-surface text-ink hover:bg-paper'}`}
          >
            {confirming ? confirmLabel : clearLabel}
          </button>
          {confirming && (
            <button type="button" onClick={() => setConfirming(false)} className="min-h-11 rounded-full px-4 text-sm font-semibold text-ink-soft hover:bg-paper">
              취소
            </button>
          )}
        </div>
      )}
    </section>
  );
}
