import { ArrowRight, Languages, Lightbulb, Volume2 } from 'lucide-react';
import { useRef, useState } from 'react';
import type { ThinkingGap } from '../lib/api';
import { WordText } from './WordText';
import { YouGlishSheet } from './YouGlishSheet';

const KIND = {
  framing: { label: '생각 방식이 달라요', Icon: Lightbulb, tone: 'bg-marker/50' },
  word: { label: '단어를 몰랐어요', Icon: Languages, tone: 'bg-paper' },
} as const;

function PronounceButton({ phrase }: { phrase: string }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`발음 듣기, ${phrase}`}
        aria-haspopup="dialog"
        className="mt-3 flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:bg-paper"
      >
        <Volume2 size={18} aria-hidden />
        발음 듣기
      </button>
      {open && <YouGlishSheet phrase={phrase} onClose={close} />}
    </>
  );
}

export function ThinkingGaps({ gaps }: { gaps?: ThinkingGap[] }) {
  if (!gaps?.length) return null;
  const sorted = [...gaps.filter((g) => g.kind === 'framing'), ...gaps.filter((g) => g.kind !== 'framing')];
  return (
    <section className="mt-8" aria-labelledby="thinking-gaps-title">
      <h3 id="thinking-gaps-title" className="mb-3 text-lg font-bold">
        생각 방식 차이
      </h3>
      <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
        {sorted.map((g, i) => {
          const { label, Icon, tone } = KIND[g.kind];
          return (
            <li key={i} className="p-4">
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>
                <Icon size={14} aria-hidden />
                {label}
              </span>
              <p className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <span lang="ko" className="text-ink-soft">
                  {g.korean}
                </span>
                <ArrowRight size={16} className="shrink-0 self-center text-ink-soft" aria-hidden />
                <span className="sr-only">영어로</span>
                <span lang="en" className="min-w-0 text-lg font-semibold break-words">
                  <span className="mark">
                    <WordText text={g.english} />
                  </span>
                </span>
              </p>
              {g.note && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{g.note}</p>}
              <PronounceButton phrase={g.english} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
