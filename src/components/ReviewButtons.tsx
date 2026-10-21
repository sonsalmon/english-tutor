import { BookmarkPlus, Check, Undo2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ReadglossOffError, type Tutoring } from '../lib/api';
import { phraseStatus, savePhrase } from '../lib/phrases';
import { flagReview, getReview, isFlagged, reviewKey, withState, type ReviewItems, type ReviewKind, type ReviewState } from '../lib/review';

export const cardKey = (text: string) => text.trim().replace(/\s+/g, ' ').toLowerCase();
export const cardable = (text: string) => text.trim().length >= 2 && text.length <= 1000 && /\p{L}/u.test(text);

export type Cards = { available: boolean; off: boolean; saved: Set<string>; mark: (text: string) => void; turnOff: () => void };

export function useCards(tutoring: Tutoring): Cards {
  const texts = useMemo(() => {
    const all = [...tutoring.corrections.map((c) => c.better), ...(tutoring.us_style ?? []).map((u) => u.natural), ...(tutoring.thinking_gaps ?? []).map((g) => g.english)].filter(cardable);
    return [...new Set(all)].slice(0, 40);
  }, [tutoring]);
  const [saved, setSaved] = useState<Set<string>>(() => new Set());
  const [off, setOff] = useState(false);

  useEffect(() => {
    if (!texts.length) return;
    let cancelled = false;
    phraseStatus(texts).then(
      (flags) => {
        if (!cancelled) setSaved(new Set(texts.filter((_, i) => flags[i]).map(cardKey)));
      },
      (e: unknown) => {
        if (!cancelled && e instanceof ReadglossOffError) setOff(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [texts]);

  return {
    available: texts.length > 0,
    off,
    saved,
    mark: (text) => setSaved((prev) => new Set(prev).add(cardKey(text))),
    turnOff: () => setOff(true),
  };
}

export type Review = {
  items: ReviewItems;
  canFlag: boolean;
  error: string | null;
  flag: (kind: ReviewKind, text: string, state: ReviewState | null) => Promise<void>;
};

export function useReview(stem?: string | null): Review {
  const [items, setItems] = useState<ReviewItems>({});
  const [error, setError] = useState<string | null>(null);
  const itemsRef = useRef(items);
  itemsRef.current = items;

  useEffect(() => {
    setItems({});
    if (!stem) return;
    const controller = new AbortController();
    getReview(stem, controller.signal).then(setItems, () => {
      // 표시를 못 읽으면 표시 없이 보여 준다.
    });
    return () => controller.abort();
  }, [stem]);

  const flag = useCallback(
    async (kind: ReviewKind, text: string, state: ReviewState | null) => {
      if (!stem) return;
      const key = reviewKey(kind, text);
      const previous = itemsRef.current[key] ?? null;
      setItems((prev) => withState(prev, key, state));
      setError(null);
      try {
        await flagReview({ stem, kind, text, state });
      } catch {
        setItems((prev) => withState(prev, key, previous));
        setError('표시하지 못했어요. 다시 눌러 주세요.');
      }
    },
    [stem],
  );

  return { items, canFlag: !!stem, error, flag };
}

export const stateOf = (review: Review, kind: ReviewKind, text: string): ReviewState | undefined => review.items[reviewKey(kind, text)];

export const dimmed = (review: Review, kind: ReviewKind, text: string): string => (isFlagged(stateOf(review, kind, text)) ? 'opacity-60' : '');

const base = 'flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold whitespace-nowrap';
const idle = `${base} border-line bg-surface text-ink hover:bg-paper disabled:text-ink-soft`;

type Choice = 'save' | 'known' | 'misheard';
const CHIP: Record<'known' | 'misheard', string> = { known: '이미 알아요', misheard: '인식 오류로 표시' };

export function ReviewButtons({
  kind,
  text,
  translation = '',
  choices,
  review,
  cards,
}: {
  kind: ReviewKind;
  text: string;
  translation?: string;
  choices: Choice[];
  review: Review;
  cards: Cards;
}) {
  const state = stateOf(review, kind, text);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function save() {
    setBusy(true);
    setFailed(false);
    try {
      await savePhrase(text, translation.trim().slice(0, 300));
      cards.mark(text);
      void review.flag(kind, text, 'saved');
    } catch (e) {
      if (e instanceof ReadglossOffError) cards.turnOff();
      else setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (state === 'known' || state === 'misheard') {
    return (
      <div className="mt-3 flex">
        <button
          type="button"
          onClick={() => void review.flag(kind, text, null)}
          aria-label={`${CHIP[state]} 표시 되돌리기, ${text}`}
          className={`${base} border-line bg-paper text-ink`}
        >
          <Undo2 size={18} aria-hidden />
          {CHIP[state]} · 되돌리기
        </button>
      </div>
    );
  }

  const savedHere = state === 'saved' || cards.saved.has(cardKey(text));
  const canSave = choices.includes('save') && !cards.off && cardable(text);
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {canSave &&
        (savedHere ? (
          <button type="button" disabled aria-label={`카드로 저장됨, ${text}`} className={`${base} border-call bg-call/10 text-ink`}>
            <Check size={18} aria-hidden />
            저장됨
          </button>
        ) : (
          <button
            type="button"
            onClick={save}
            disabled={busy}
            aria-label={`${failed ? '카드로 저장 다시 시도' : '카드로 저장'}, ${text}`}
            className={idle}
          >
            <BookmarkPlus size={18} aria-hidden />
            {busy ? '저장 중' : failed ? '저장하지 못했어요. 다시 시도' : '저장'}
          </button>
        ))}
      {review.canFlag && choices.includes('known') && (
        <button type="button" onClick={() => void review.flag(kind, text, 'known')} aria-label={`이미 알아요로 표시, ${text}`} className={idle}>
          이미 알아요
        </button>
      )}
      {review.canFlag && choices.includes('misheard') && (
        <button type="button" onClick={() => void review.flag(kind, text, 'misheard')} aria-label={`인식이 틀렸어요로 표시, ${text}`} className={idle}>
          인식이 틀렸어요
        </button>
      )}
    </div>
  );
}
