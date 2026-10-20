import { LoaderCircle, Phone, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
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

const CAUSES: Record<string, string> = {
  english: '영어 표현',
  understanding: '내용 이해',
  both: '둘 다',
  unclear: '원인 불분명',
};

function duration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`;
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface">{children}</div>
    </section>
  );
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
      ...(call.setup.kind === 'teachback' ? { mode: 'teachback' as const, lesson_date: call.setup.lessonDate } : {}),
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

      {tutoring && (
        <>
          {tutoring.corrections.length > 0 && (
            <Block title="고쳐 말하기">
              {tutoring.corrections.map((c, i) => (
                <div key={i} className="p-4">
                  <p className="text-ink-soft line-through decoration-ink-soft/50">{c.said}</p>
                  <p className="mt-1 text-lg font-semibold">
                    <span className="mark">{c.better}</span>
                  </p>
                  {c.why && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{c.why}</p>}
                </div>
              ))}
            </Block>
          )}
          {tutoring.good.length > 0 && (
            <Block title="잘한 표현">
              {tutoring.good.map((g, i) => (
                <div key={i} className="p-4">
                  <p className="font-semibold">{g.said}</p>
                  {g.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{g.note}</p>}
                </div>
              ))}
            </Block>
          )}
          {tutoring.vocab.length > 0 && (
            <Block title="기억할 단어">
              {tutoring.vocab.map((v, i) => (
                <div key={i} className="p-4">
                  <p>
                    <span className="font-semibold">{v.word}</span>
                    {v.meaning_ko && <span className="ml-2 text-ink-soft">{v.meaning_ko}</span>}
                  </p>
                  {v.example && <p className="mt-1 text-sm text-ink-soft">{v.example}</p>}
                </div>
              ))}
            </Block>
          )}
          {tutoring.pragmatics.length > 0 && (
            <Block title="미국식으로 말하기">
              {tutoring.pragmatics.map((p, i) => (
                <div key={i} className="p-4">
                  <p className="font-semibold">{p.pattern}</p>
                  {p.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{p.note}</p>}
                </div>
              ))}
            </Block>
          )}
          {isTeachback && (tutoring.unanswered?.length ?? 0) > 0 && (
            <Block title="답하지 못한 질문">
              {tutoring.unanswered!.map((u, i) => (
                <div key={i} className="p-4">
                  <p className="font-semibold">{u.question}</p>
                  {u.evidence && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{u.evidence}</p>}
                  <span className="mt-2 inline-block rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">{CAUSES[u.cause] ?? u.cause}</span>
                </div>
              ))}
            </Block>
          )}
          {retry?.goal && (
            <section className="mt-8 rounded-2xl bg-ink p-5 text-white">
              <h2 className="text-sm font-semibold text-white/70">다음 통화 목표</h2>
              <p className="mt-2 leading-relaxed">{retry.goal}</p>
              {!!retry.target_phrases?.length && (
                <p className="mt-3 text-sm text-white/80">{retry.target_phrases.map((p) => `“${p}”`).join('  ')}</p>
              )}
            </section>
          )}
        </>
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
