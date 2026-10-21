import { BookmarkPlus, Check, Volume2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { formatUsd, ReadglossOffError, type Cost, type Tutoring } from '../lib/api';
import { phraseStatus, savePhrase } from '../lib/phrases';
import { isSingleWord, wordCount, type Unit } from '../lib/units';
import { StarButton } from './StarButton';
import { WordText, WordUnitsProvider } from './WordText';
import { YouGlishSheet } from './YouGlishSheet';

const CAUSES: Record<string, string> = {
  english: '영어 표현',
  understanding: '내용 이해',
  both: '둘 다',
  unclear: '원인 불분명',
};

const cardKey = (text: string) => text.trim().replace(/\s+/g, ' ').toLowerCase();
const cardable = (text: string) => text.trim().length >= 2 && text.length <= 1000 && /\p{L}/u.test(text);

type Cards = { available: boolean; off: boolean; saved: Set<string>; mark: (text: string) => void; turnOff: () => void };

function useCards(tutoring: Tutoring): Cards {
  const texts = useMemo(() => {
    const all = [...tutoring.corrections.map((c) => c.better), ...tutoring.good.map((g) => g.said)].filter(cardable);
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

function CardButton({ text, translation, cards }: { text: string; translation: string; cards: Cards }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  if (cards.off || !cardable(text)) return null;
  const done = cards.saved.has(cardKey(text));

  async function save() {
    setBusy(true);
    setFailed(false);
    try {
      await savePhrase(text, translation.trim().slice(0, 300));
      cards.mark(text);
    } catch (e) {
      if (e instanceof ReadglossOffError) cards.turnOff();
      else setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  const base = 'flex min-h-11 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold whitespace-nowrap';
  return (
    <div className="mt-3">
      {done ? (
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
          className={`${base} border-line bg-surface text-ink hover:bg-paper disabled:text-ink-soft`}
        >
          <BookmarkPlus size={18} aria-hidden />
          {busy ? '저장 중' : failed ? '저장하지 못했어요. 다시 시도' : '카드로 저장'}
        </button>
      )}
    </div>
  );
}

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

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h3 className="mb-3 text-lg font-bold">{title}</h3>
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface">{children}</div>
    </section>
  );
}

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
        className="-my-1 flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:bg-paper"
      >
        <Volume2 size={18} aria-hidden />
        발음 듣기
      </button>
      {open && <YouGlishSheet phrase={phrase} onClose={close} />}
    </>
  );
}

export function TutoringBlocks({ tutoring, isTeachback }: { tutoring: Tutoring; isTeachback: boolean }) {
  const retry = tutoring.retry;
  const cards = useCards(tutoring);
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
      {tutoring.corrections.length > 0 && (
        <Block title="고쳐 말하기">
          {tutoring.corrections.map((c, i) => (
            <div key={i} className="p-4">
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
              <CardButton text={c.better} translation={c.why} cards={cards} />
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
                <PronounceButton phrase={g.said} />
              </div>
              {g.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{g.note}</p>}
              <CardButton text={g.said} translation={g.note} cards={cards} />
            </div>
          ))}
        </Block>
      )}
      {tutoring.vocab.length > 0 && (
        <Block title="기억할 단어">
          {tutoring.vocab.map((v, i) => (
            <div key={i} className="p-4">
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
            </div>
          ))}
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
