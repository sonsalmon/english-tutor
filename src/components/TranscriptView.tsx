import { ChevronDown, ChevronUp, History } from 'lucide-react';
import { useState } from 'react';
import type { Turn } from '../lib/api';
import { PARTNERS } from '../lib/partners';
import { WordText } from './WordText';

const COLLAPSED_TURNS = 6;

function partnerName(voice: string | null | undefined): string {
  return PARTNERS.find((p) => p.voice === voice)?.name ?? '상대';
}

const toggleClass =
  'flex min-h-11 w-full items-center justify-center gap-1.5 rounded-b-2xl border-t border-line px-4 text-sm font-semibold text-ink hover:bg-paper';

export function TranscriptView({ turns, verbatim, voice }: { turns: Turn[]; verbatim: string | null; voice?: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!turns.length && !verbatim) return null;
  const long = turns.length > COLLAPSED_TURNS;
  const shown = expanded || !long ? turns : turns.slice(0, COLLAPSED_TURNS);
  const partner = partnerName(voice);

  return (
    <section className="mt-8">
      <h3 className="mb-3 text-lg font-bold">대화 전문</h3>
      {turns.length > 0 && (
        <div className="rounded-2xl border border-line bg-surface">
          <ol className="divide-y divide-line">
            {shown.map((turn, i) => (
              <li key={i} className="px-4 py-3">
                <p className={`text-sm font-semibold ${turn.speaker === 'me' ? 'text-call-press' : 'text-ink-soft'}`}>
                  {turn.speaker === 'me' ? '나' : partner}
                </p>
                <p className="mt-0.5 leading-relaxed break-words">
                  <WordText text={turn.text} />
                </p>
              </li>
            ))}
          </ol>
          {long && (
            <button type="button" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)} className={toggleClass}>
              {expanded ? (
                <>
                  <ChevronUp size={18} aria-hidden />
                  접기
                </>
              ) : (
                <>
                  <ChevronDown size={18} aria-hidden />
                  전체 보기 ({turns.length}턴)
                </>
              )}
            </button>
          )}
        </div>
      )}
      {verbatim && (
        <details className="group mt-3 rounded-2xl border border-line bg-surface">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 font-semibold [&::-webkit-details-marker]:hidden">
            <span>내가 실제로 한 말(받아쓰기 그대로)</span>
            <ChevronDown size={18} className="shrink-0 text-ink-soft transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <p lang="en" className="border-t border-line px-4 py-3 leading-relaxed break-words whitespace-pre-wrap text-ink-soft">
            {verbatim.trim()}
          </p>
        </details>
      )}
    </section>
  );
}

export function ReplayButton({ stem }: { stem: string }) {
  return (
    <button
      type="button"
      onClick={() => {
        window.location.hash = '#/replay/' + stem;
      }}
      className="mt-8 flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-ink px-6 font-bold text-white hover:bg-ink/90 active:bg-ink/80 lg:w-auto lg:min-w-64"
    >
      <History size={20} aria-hidden />
      이 대화 그대로 다시 연습
    </button>
  );
}
