import { Check, LoaderCircle, Phone, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { TutoringBlocks } from '../components/TutoringBlocks';
import { CallButton, QuietButton, Screen } from '../components/ui';
import { requestTutoring, type Tutoring } from '../lib/api';
import type { Retry } from '../lib/instructions';
import { go } from '../lib/router';
import { callTitle, type FinishedCall } from '../lib/setup';

const LEVELS: Record<number, { name: string; desc: string }> = {
  1: { name: 'Tiro', desc: '도움을 많이 받았어요' },
  2: { name: 'Proficiens', desc: '조금 도움을 받았어요' },
  3: { name: 'Peritus', desc: '도움 없이 자연스러웠어요' },
};

function ReadingWords({ words, used, saved }: { words: string[]; used: string[]; saved: number }) {
  if (!words.length && !saved) return null;
  return (
    <section className="mt-8">
      <h2 className="text-lg font-bold">읽다가 찾아본 단어</h2>
      {words.length > 0 && (
        <>
          <p className="mt-1 text-ink-soft">
            {used.length
              ? `${words.length}개 중 ${used.length}개를 통화에서 썼어요.`
              : '이번 통화에서는 아직 못 썼어요. 다음 통화에서 써 봐요.'}
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {words.map((w) => {
              const ok = used.includes(w);
              return (
                <li
                  key={w}
                  lang="en"
                  className={`flex items-center gap-1 rounded-full border px-3 py-1.5 text-[15px] ${ok ? 'border-call bg-call/10 font-semibold' : 'border-line bg-surface text-ink-soft'}`}
                >
                  {ok && <Check size={14} aria-hidden />}
                  {w}
                  {ok && <span className="sr-only"> (썼어요)</span>}
                </li>
              );
            })}
          </ul>
        </>
      )}
      {saved > 0 && (
        <p className="mt-3 text-sm leading-relaxed text-ink-soft">
          이번 통화의 새 단어와 고친 표현 {saved}개를 readgloss 단어장에 넣었어요. 읽을 때 복습에 나와요.
        </p>
      )}
    </section>
  );
}

function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}

export function Summary({ call, onRetry }: { call: FinishedCall; onRetry: (retry: Retry) => void }) {
  const [tutoring, setTutoring] = useState<Tutoring | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isTeachback = call.setup.kind === 'teachback';

  const load = useCallback(() => {
    setError(null);
    setTutoring(null);
    requestTutoring({
      started_at: call.startedAt,
      ...(call.setup.kind === 'teachback'
        ? { mode: 'teachback' as const, lesson_date: call.setup.lessonDate }
        : { practice_words: call.practiceWords }),
    })
      .then(setTutoring)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '튜터링 분석에 실패했어요.'));
  }, [call]);

  useEffect(load, [load]);

  const level = call.result ? LEVELS[call.result.score] : undefined;
  const retry: Retry | null = tutoring
    ? isTeachback
      ? { ...tutoring.retry, unanswered: tutoring.unanswered }
      : tutoring.retry
    : null;
  const canRetry = !!retry && (isTeachback || !!retry.goal || !!retry.target_phrases?.length);

  return (
    <Screen>
      <header className="flex h-11 items-center">
        <span className="text-sm font-semibold text-ink-soft">통화 요약</span>
      </header>
      <h1 className="mt-2 text-[28px] font-bold leading-tight">통화가 끝났어요</h1>
      <p className="mt-1 text-ink-soft">
        {callTitle(call.setup)}, {duration(call.endedAt - call.startedAt)}
      </p>
      {call.endReason === 'time_limit' && <p className="mt-2 text-sm text-ink-soft">통화 시간이 다 되어 자동으로 끊었어요.</p>}
      {call.endReason === 'dropped' && <p className="mt-2 text-sm text-ink-soft">연결이 끊어져 통화를 마쳤어요.</p>}

      {call.result && (
        <section className="mt-6 rounded-2xl border border-line bg-surface p-5">
          <div className="flex items-baseline gap-3">
            <span className="text-2xl font-bold">{level?.name ?? `${call.result.score}점`}</span>
            <span className="text-ink-soft">{level?.desc}</span>
          </div>
          <div className="mt-2 flex gap-1.5" aria-label={`3단계 중 ${call.result.score}단계`}>
            {[1, 2, 3].map((n) => (
              <span key={n} className={`h-1.5 flex-1 rounded-full ${n <= call.result!.score ? 'bg-call' : 'bg-line'}`} />
            ))}
          </div>
          {call.result.feedback_pointers.length > 0 && (
            <ul className="mt-4 space-y-2 leading-relaxed">
              {call.result.feedback_pointers.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      {!tutoring && !error && (
        <div className="mt-10 flex flex-col items-center gap-3 text-center text-ink-soft" role="status">
          <LoaderCircle size={28} className="animate-spin" aria-hidden />
          <p>Ms. Park이 통화를 정리하고 있어요. 30초쯤 걸려요.</p>
        </div>
      )}

      {error && (
        <div className="mt-8 rounded-2xl border border-line bg-surface p-5">
          <p className="text-end-press">{error}</p>
          <div className="mt-4">
            <QuietButton onClick={load}>
              <RotateCcw size={18} aria-hidden />
              다시 정리하기
            </QuietButton>
          </div>
        </div>
      )}

      {tutoring && <TutoringBlocks tutoring={tutoring} isTeachback={isTeachback} />}
      {tutoring && (
        <ReadingWords words={call.practiceWords} used={tutoring.practice_used ?? []} saved={tutoring.readgloss?.saved ?? 0} />
      )}

      <div className="mt-auto space-y-3 pt-10">
        {canRetry && retry && (
          <CallButton onClick={() => onRetry(retry)}>
            <Phone size={22} aria-hidden />
            {isTeachback ? '같은 수업 다시 하기' : '같은 장면 다시 통화'}
          </CallButton>
        )}
        <QuietButton onClick={() => go('home')}>홈으로</QuietButton>
      </div>
    </Screen>
  );
}
