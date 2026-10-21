import { useMemo, type ReactNode } from 'react';
import { formatUsd, type Cost, type Tutoring } from '../lib/api';
import { isSingleWord, wordCount, type Unit } from '../lib/units';
import { PronounceButton } from './PronounceButton';
import { ReviewButtons, dimmed, useCards, useReview } from './ReviewButtons';
import { StarButton } from './StarButton';
import { UsStyle } from './UsStyle';
import { WordText, WordUnitsProvider } from './WordText';

const CAUSES: Record<string, string> = {
  english: '영어 표현',
  understanding: '내용 이해',
  both: '둘 다',
  unclear: '원인 불분명',
};

export function CostLine({ cost, pending = false, className = '' }: { cost?: Cost | null; pending?: boolean; className?: string }) {
  if (pending) {
    return (
      <p className={`text-sm text-ink-soft ${className}`} role="status">
        예상 비용 계산 중
      </p>
    );
  }
  if (!cost || cost.total == null) return null;
  const parts = cost.live != null && cost.tutoring != null ? ` (통화 ${formatUsd(cost.live)} + 정리 ${formatUsd(cost.tutoring)})` : '';
  return (
    <p className={`text-sm text-ink-soft ${className}`}>
      예상 비용 약 {formatUsd(cost.total)}
      {parts} · 실제 청구와 다를 수 있어요
    </p>
  );
}

function Block({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h3 className={subtitle ? 'text-lg font-bold' : 'mb-3 text-lg font-bold'}>{title}</h3>
      {subtitle && <p className="mt-0.5 mb-3 text-sm text-ink-soft">{subtitle}</p>}
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface">{children}</div>
    </section>
  );
}

export function TutoringBlocks({ tutoring, isTeachback, stem }: { tutoring: Tutoring; isTeachback: boolean; stem?: string | null }) {
  const retry = tutoring.retry;
  const cards = useCards(tutoring);
  const review = useReview(stem);
  const usStyle = tutoring.us_style ?? [];
  const units = useMemo<Unit[]>(
    () => tutoring.vocab.filter((v) => wordCount(v.word) >= 2).map((v) => ({ text: v.word, gloss: v.meaning_ko })),
    [tutoring.vocab],
  );
  return (
    <WordUnitsProvider value={units}>
      {cards.off && cards.available && (
        <p className="mt-6 text-sm text-ink-soft" role="status">
          readgloss가 꺼져 있어 카드로 저장할 수 없어요.
        </p>
      )}
      {review.error && (
        <p className="mt-4 text-sm text-ink-soft" role="alert">
          {review.error}
        </p>
      )}
      {tutoring.corrections.length > 0 && (
        <Block title="고쳐 말하기">
          {tutoring.corrections.map((c, i) => (
            <div key={i} className={`p-4 ${dimmed(review, 'correction', c.better)}`}>
              <p className="text-ink-soft line-through decoration-ink-soft/50">
                <WordText text={c.said} />
              </p>
              <div className="mt-1 flex items-start justify-between gap-3">
                <p className="min-w-0 text-lg font-semibold">
                  <span className="mark">
                    <WordText text={c.better} />
                  </span>
                </p>
                <PronounceButton phrase={c.better} />
              </div>
              {c.why && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{c.why}</p>}
              <ReviewButtons kind="correction" text={c.better} translation={c.why} choices={['save', 'known', 'misheard']} review={review} cards={cards} />
            </div>
          ))}
        </Block>
      )}
      {tutoring.good.length > 0 && (
        <Block title="잘한 표현">
          {tutoring.good.map((g, i) => (
            <div key={i} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 font-semibold">
                  <WordText text={g.said} />
                </p>
                <div className="-my-1 flex shrink-0 items-center gap-2">
                  <PronounceButton phrase={g.said} />
                  <StarButton kind={isSingleWord(g.said) ? 'word' : 'phrase'} text={g.said} gloss={g.note} />
                </div>
              </div>
              {g.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{g.note}</p>}
            </div>
          ))}
        </Block>
      )}
      {tutoring.vocab.length > 0 && (
        <Block title="기억할 단어">
          {tutoring.vocab.map((v, i) => (
            <div key={i} className={`p-4 ${dimmed(review, 'vocab', v.word)}`}>
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0">
                  <span className="font-semibold">
                    <WordText text={v.word} />
                  </span>
                  {v.meaning_ko && <span className="ml-2 text-ink-soft">{v.meaning_ko}</span>}
                </p>
                <div className="-my-1 flex shrink-0 items-center gap-2">
                  <PronounceButton phrase={v.word} />
                  <StarButton
                    kind={isSingleWord(v.word) ? 'word' : 'phrase'}
                    text={v.word}
                    gloss={v.meaning_ko}
                    sentence={v.example}
                  />
                </div>
              </div>
              {v.example && (
                <p className="mt-1 text-sm text-ink-soft">
                  <WordText text={v.example} />
                </p>
              )}
              <ReviewButtons kind="vocab" text={v.word} choices={['known']} review={review} cards={cards} />
            </div>
          ))}
        </Block>
      )}
      {usStyle.length > 0 && (
        <Block title="미국식으로 말하기" subtitle="내가 놓친 것만 골랐어요">
          <UsStyle items={usStyle} review={review} cards={cards} />
        </Block>
      )}
      {tutoring.pragmatics.length > 0 && (
        <Block title="미국식으로 말하기">
          {tutoring.pragmatics.map((p, i) => (
            <div key={i} className="p-4">
              <p className="font-semibold">
                <WordText text={p.pattern} />
              </p>
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
          <h3 className="text-sm font-semibold text-white/70">다음 통화 목표</h3>
          <p className="mt-2 leading-relaxed">
            <WordText text={retry.goal} />
          </p>
          {!!retry.target_phrases?.length && (
            <p className="mt-3 text-sm text-white/80">{retry.target_phrases.map((p, i) => (
                <span key={i} className="mr-3 inline-block">
                  “<WordText text={p} />”
                </span>
              ))}</p>
          )}
        </section>
      )}
    </WordUnitsProvider>
  );
}
