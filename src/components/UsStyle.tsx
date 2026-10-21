import { Check, ChevronDown } from 'lucide-react';
import { useState } from 'react';
import type { UsStyleItem } from '../lib/api';
import { PhraseClips } from './ClipList';
import { PronounceButton } from './PronounceButton';
import { ReviewButtons, dimmed, stateOf, type Cards, type Review } from './ReviewButtons';

const BADGE: Record<string, string> = { saved: '저장됨', known: '이미 알아요', misheard: '인식 오류로 표시' };

function Row({ item, review, cards }: { item: UsStyleItem; review: Review; cards: Cards }) {
  const [open, setOpen] = useState(false);
  const state = stateOf(review, 'us_style', item.natural);
  const panelId = `us-style-${item.natural.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
  return (
    <div className={dimmed(review, 'us_style', item.natural)}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex min-h-14 w-full items-center justify-between gap-3 p-4 text-left hover:bg-paper"
      >
        <span className="min-w-0">
          <span lang="en" className="block text-sm break-words text-ink-soft">
            {item.said}
          </span>
          <span lang="en" className="mt-0.5 block text-lg leading-snug font-semibold break-words">
            <span className="mark">{item.natural}</span>
          </span>
          {state && (
            <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">
              {state === 'saved' && <Check size={12} aria-hidden />}
              {BADGE[state]}
            </span>
          )}
        </span>
        <ChevronDown size={22} aria-hidden className={`shrink-0 text-ink-soft transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div id={panelId} className="px-4 pt-1 pb-4">
          {item.korean_way && (
            <>
              <h5 className="text-sm font-semibold text-ink-soft">한국식 생각</h5>
              <p className="mt-1 leading-relaxed">{item.korean_way}</p>
            </>
          )}
          {item.why && (
            <>
              <h5 className="mt-3 text-sm font-semibold text-ink-soft">왜 다른가요</h5>
              <p className="mt-1 leading-relaxed">{item.why}</p>
            </>
          )}
          <div className="mt-3 flex">
            <PronounceButton phrase={item.natural} />
          </div>
          <PhraseClips phrase={item.natural} />
          <ReviewButtons kind="us_style" text={item.natural} translation={item.why} choices={['save', 'known']} review={review} cards={cards} />
        </div>
      )}
    </div>
  );
}

export function UsStyle({ items, review, cards }: { items: UsStyleItem[]; review: Review; cards: Cards }) {
  return (
    <>
      {items.map((item, i) => (
        <Row key={`${i}-${item.natural}`} item={item} review={review} cards={cards} />
      ))}
    </>
  );
}
