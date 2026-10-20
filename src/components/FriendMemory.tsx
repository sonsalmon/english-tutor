import { useState } from 'react';
import { clearPartnerMemory, forgetPartnerMemoryItem, type PartnerMemory, type PartnerMemoryKind } from '../lib/api';

export type MemoryState = { status: 'loading' } | { status: 'failed' } | { status: 'ready'; memory: PartnerMemory | null };

// 한국어 발음 기준 조사: 카르멘은 받침이 있어 '이', 나머지는 '가'.
function subject(id: string): string {
  return id === 'carmen' ? '이' : '가';
}

function ForgetButton({ label, onClick, disabled }: { label: string; onClick: () => void; disabled: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
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
  const memory = state.status === 'ready' ? state.memory : null;
  const empty = !memory || (memory.facts.length === 0 && memory.threads.length === 0);

  const forget = async (kind: PartnerMemoryKind, index: number) => {
    setBusy(true);
    setProblem('');
    setConfirming(false);
    try {
      onChange(await forgetPartnerMemoryItem(partnerId, kind, index));
    } catch (e) {
      setProblem(e instanceof Error ? e.message : '기억을 지우지 못했어요.');
    } finally {
      setBusy(false);
    }
  };

  const clearAll = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setBusy(true);
    setProblem('');
    try {
      await clearPartnerMemory(partnerId);
      onChange(null);
      setConfirming(false);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : '기억을 지우지 못했어요.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="friend-memory-title" className="mt-5 rounded-2xl border border-line bg-surface p-4 lg:mt-6 lg:p-5">
      <h2 id="friend-memory-title" className="text-lg font-bold">
        {name}
        {subject(partnerId)} 기억하는 것
      </h2>

      {state.status === 'loading' && <p className="mt-2 text-ink-soft">기억을 불러오는 중이에요.</p>}
      {state.status === 'failed' && <p className="mt-2 text-ink-soft">지금은 기억을 볼 수 없어요. 통화는 그대로 할 수 있어요.</p>}
      {state.status === 'ready' && empty && (
        <p className="mt-2 text-ink-soft">
          아직 나눈 이야기가 없어요. 통화가 끝나면 {name}
          {subject(partnerId)} 기억해요.
        </p>
      )}

      {memory && memory.threads.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">다음에 이어 갈 이야기</h3>
          <ul className="divide-y divide-line">
            {memory.threads.map((t, i) => (
              <li key={`${t.text}-${i}`} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{t.ko}</span>
                  <span className="block text-sm text-ink-soft">{t.text}</span>
                </span>
                <ForgetButton label={t.ko} disabled={busy} onClick={() => void forget('threads', i)} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {memory && memory.facts.length > 0 && (
        <div className="mt-3">
          <h3 className="text-sm font-semibold text-ink-soft">알게 된 것</h3>
          <ul className="divide-y divide-line">
            {memory.facts.map((f, i) => (
              <li key={`${f.text}-${i}`} className="flex items-center gap-2 py-2">
                <span className="min-w-0 flex-1 text-[15px]">{f.text}</span>
                <ForgetButton label={f.text} disabled={busy} onClick={() => void forget('facts', i)} />
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

      {!empty && (
        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={() => void clearAll()}
            disabled={busy}
            className={`min-h-11 rounded-full border px-5 text-sm font-semibold disabled:opacity-50 ${confirming ? 'border-end bg-end text-white active:bg-end-press' : 'border-line bg-surface text-ink hover:bg-paper'}`}
          >
            {confirming ? '정말 지울까요?' : '기억 모두 지우기'}
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
