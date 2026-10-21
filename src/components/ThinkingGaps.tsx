import { ArrowRight, Check, ChevronDown, Languages, Lightbulb } from 'lucide-react';
import { useId, useState } from 'react';
import type { ThinkingGap, Tutoring } from '../lib/api';
import { PhraseClips } from './ClipList';
import { PronounceButton } from './PronounceButton';
import { ReviewButtons, dimmed, stateOf, useCards, useReview, type Cards, type Review } from './ReviewButtons';
import { WordText } from './WordText';

const KIND = {
  framing: { label: '생각 방식이 달라요', Icon: Lightbulb, tone: 'bg-marker/50' },
  word: { label: '단어를 몰랐어요', Icon: Languages, tone: 'bg-paper' },
} as const;

const BADGE: Record<string, string> = { saved: '저장됨', known: '이미 알아요', misheard: '인식 오류로 표시' };

function Row({ gap, review, cards }: { gap: ThinkingGap; review: Review; cards: Cards }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { label, Icon, tone } = KIND[gap.kind];
  const state = stateOf(review, 'thinking_gap', gap.english);
  return (
    <li className={dimmed(review, 'thinking_gap', gap.english)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex min-h-14 w-full items-center justify-between gap-3 p-4 text-left hover:bg-paper"
      >
        <span className="min-w-0">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
            <Icon size={14} aria-hidden />
            {label}
          </span>
          <span className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span lang="ko" className="text-ink-soft">
              {gap.korean}
            </span>
            <ArrowRight size={16} className="shrink-0 self-center text-ink-soft" aria-hidden />
            <span className="sr-only">영어로</span>
            <span lang="en" className="min-w-0 text-lg font-semibold break-words">
              <span className="mark">{gap.english}</span>
            </span>
          </span>
          {state && (
            <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">
              {state === 'saved' && <Check size={12} aria-hidden />}
              {BADGE[state]}
            </span>
          )}
        </span>
        <ChevronDown size={22} aria-hidden className={`shrink-0 text-ink-soft transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div id={panelId} className="px-4 pt-1 pb-4">
          {gap.note && <p className="leading-relaxed">{gap.note}</p>}
          {gap.detail && (
            <>
              <h5 className="mt-3 text-sm font-semibold text-ink-soft">자세히</h5>
              <p className="mt-1 leading-relaxed">{gap.detail}</p>
            </>
          )}
          {gap.examples && gap.examples.length > 0 && (
            <>
              <h5 className="mt-3 text-sm font-semibold text-ink-soft">예문</h5>
              <ul className="mt-1 space-y-1">
                {gap.examples.map((ex, i) => (
                  <li key={i} lang="en" className="leading-relaxed break-words">
                    <WordText text={ex} />
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-3 flex">
            <PronounceButton phrase={gap.english} />
          </div>
          <PhraseClips phrase={gap.english} />
          <ReviewButtons
            kind="thinking_gap"
            text={gap.english}
            translation={gap.korean}
            choices={['save', 'known', 'misheard']}
            review={review}
            cards={cards}
          />
        </div>
      )}
    </li>
  );
}

export function ThinkingGaps({ tutoring, stem }: { tutoring: Tutoring; stem?: string | null }) {
  const cards = useCards(tutoring);
  const review = useReview(stem);
  const gaps = tutoring.thinking_gaps;
  if (!gaps?.length) return null;
  const sorted = [...gaps.filter((g) => g.kind === 'framing'), ...gaps.filter((g) => g.kind !== 'framing')];
  return (
    <section className="mt-8" aria-labelledby="thinking-gaps-title">
      <h3 id="thinking-gaps-title" className="text-lg font-bold">
        생각 방식 차이
      </h3>
      <p className="mt-0.5 mb-3 text-sm text-ink-soft">눌러서 자세한 설명과 예시를 보세요</p>
      <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
        {sorted.map((g, i) => (
          <Row key={`${i}-${g.english}`} gap={g} review={review} cards={cards} />
        ))}
      </ul>
      {review.error && (
        <p className="mt-2 text-sm text-end-press" role="alert">
          {review.error}
        </p>
      )}
    </section>
  );
}
