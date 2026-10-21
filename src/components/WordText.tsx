import { Link2 } from 'lucide-react';
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { SaveSource } from '../lib/api';
import { isPhraseSaved, onSaved as subscribeSaved, phraseKey } from '../lib/phrases';
import { extendRange, findUnits, lookupForm, MAX_PHRASE_WORDS, phraseCandidates, pickRange, WORD_TOKEN, type Range, type Unit } from '../lib/units';
import { WordPopover } from './WordPopover';
import { YouGlishSheet } from './YouGlishSheet';

const SENTENCE_END = /[.!?]+["')\]”’]*(?=\s|$)/;

function sentenceAround(text: string, index: number, length: number): string {
  let start = 0;
  for (const m of text.matchAll(/[.!?]+["')\]”’]*\s+/g)) {
    const end = m.index + m[0].length;
    if (end > index) break;
    start = end;
  }
  const rest = text.slice(index + length);
  const stop = SENTENCE_END.exec(rest);
  const end = stop ? index + length + stop.index + stop[0].length : text.length;
  return text.slice(start, end).trim().slice(0, 1000);
}

type Active = {
  kind: 'word' | 'phrase';
  text: string;
  gloss?: string;
  sentence: string;
  anchor: HTMLElement;
  range: Range;
};

type Piece = { index: number; length: number; label: string; word?: string; unit?: Unit; saved?: boolean; selected?: boolean };

const UnitsContext = createContext<Unit[]>([]);

// 아래 WordText 전부에 같은 구 목록을 적용한다(한 화면의 여러 문장이 같은 목록을 쓸 때).
export const WordUnitsProvider = UnitsContext.Provider;

// units: 알려진 두 낱말 이상 표현(뜻이 있으면 함께). 문장에서 먼저 찾아 낱말 대신 하나의 버튼으로 만든다. 없으면 WordUnitsProvider의 목록을 쓴다.
// onOpenChange: 단어 시트나 발음 시트가 열리고 닫힐 때 알린다(재생기가 영상을 멈췄다 되돌리는 데 쓴다).
// source: 이 글이 영상 자막이면 그 영상과 시각. 여기서 저장한 단어·표현에 출처로 붙는다.
// learn: 영상 자막처럼 공부하는 글. 이미 저장한 표현에 실선 밑줄을 긋고, '구로 묶기'(이어진 단어를 차례로 탭해 구로 저장)를 붙인다.
export function WordText({
  text,
  units,
  onOpenChange,
  source,
  learn = false,
}: {
  text: string;
  units?: Unit[];
  onOpenChange?: (open: boolean) => void;
  source?: SaveSource;
  learn?: boolean;
}) {
  const inherited = useContext(UnitsContext);
  const [active, setActive] = useState<Active | null>(null);
  const [phrase, setPhrase] = useState<string | null>(null);
  const [pick, setPick] = useState(false);
  const [sel, setSel] = useState<Range | null>(null);
  const [savedKeys, setSavedKeys] = useState<ReadonlySet<string>>(new Set());
  const lastAnchor = useRef<HTMLElement | null>(null);
  const pickToggle = useRef<HTMLButtonElement>(null);
  const fromPick = useRef(false);
  const open = active !== null || phrase !== null || pick;
  const notify = useRef(onOpenChange);
  notify.current = onOpenChange;
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current === open) return;
    wasOpen.current = open;
    notify.current?.(open);
  }, [open]);

  // 이 줄의 2~4단어 조합 중 단어장에 이미 있는 것(한 번에 묻는다). 읽기 실패는 밑줄 없음으로 둔다.
  useEffect(() => {
    if (!learn) return;
    let cancelled = false;
    const candidates = phraseCandidates(text);
    Promise.all(candidates.map((c) => isPhraseSaved(c).catch(() => false))).then((flags) => {
      if (!cancelled) setSavedKeys(new Set(candidates.filter((_, i) => flags[i])));
    });
    return () => {
      cancelled = true;
    };
  }, [learn, text]);
  useEffect(() => {
    if (!learn) return;
    return subscribeSaved((key) => {
      if (key.startsWith('p:')) setSavedKeys((prev) => new Set(prev).add(key.slice(2)));
    });
  }, [learn]);

  const knownUnits = units ?? inherited;
  const matches = findUnits(text, savedKeys.size ? [...knownUnits, ...[...savedKeys].map((t) => ({ text: t }))] : knownUnits);
  const pieces: Piece[] = matches.map((m) => {
    const label = text.slice(m.index, m.index + m.length);
    return { index: m.index, length: m.length, label, unit: m.unit, saved: learn && savedKeys.has(phraseKey(label)) };
  });
  for (const m of text.matchAll(WORD_TOKEN)) {
    const word = lookupForm(m[0]);
    if (!word || matches.some((u) => m.index >= u.index && m.index < u.index + u.length)) continue;
    pieces.push({ index: m.index, length: m[0].length, label: m[0], word });
  }
  pieces.sort((a, b) => a.index - b.index);
  for (const p of pieces) p.selected = sel !== null && p.index < sel.end && p.index + p.length > sel.start;

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const p of pieces) {
    if (p.index > cursor) nodes.push(text.slice(cursor, p.index));
    const range = { start: p.index, end: p.index + p.length };
    const sentence = sentenceAround(text, p.index, p.length);
    const open = (anchor: HTMLElement) => {
      lastAnchor.current = anchor;
      fromPick.current = false;
      setActive(
        p.unit
          ? { kind: 'phrase', text: p.label.replace(/\s+/g, ' '), gloss: p.unit.gloss, sentence, anchor, range }
          : { kind: 'word', text: p.word!, sentence, anchor, range },
      );
    };
    nodes.push(
      <button
        key={p.index}
        type="button"
        lang="en"
        data-word={p.unit ? undefined : ''}
        data-phrase={p.unit ? '' : undefined}
        data-saved={p.saved ? '' : undefined}
        aria-haspopup={pick ? undefined : 'dialog'}
        aria-pressed={pick ? p.selected : undefined}
        onClick={(e) => {
          e.stopPropagation();
          if (pick) setSel(pickRange(text, sel, range));
          else open(e.currentTarget);
        }}
        className={`pointer-events-auto inline cursor-pointer rounded-sm text-left underline-offset-4 ${
          p.selected
            ? 'bg-marker text-ink'
            : p.saved
              ? 'underline decoration-solid decoration-[3px]'
              : p.unit
                ? 'underline decoration-dotted decoration-2'
                : 'hover:underline hover:decoration-dotted'
        }`}
      >
        {p.label}
        {p.saved && <span className="sr-only"> (저장함)</span>}
      </button>,
    );
    cursor = p.index + p.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));

  // 닫힌 시트의 포커스가 돌아갈 고시. 묶은 구를 저장하던 시트는 '이 구 저장' 버튼이 곳 사라지므로 '구로 묶기' 버튼으로 되돌린다.
  function focusTarget(): HTMLElement | null {
    return fromPick.current ? pickToggle.current : lastAnchor.current;
  }

  function restoreFocus() {
    const anchor = focusTarget();
    if (anchor?.isConnected && document.activeElement?.closest('[data-word-popover]')) anchor.focus({ preventScroll: true });
  }

  function extend(side: 'before' | 'after') {
    if (!active) return;
    const range = extendRange(text, active.range, side);
    if (!range) return;
    setActive({
      ...active,
      kind: 'phrase',
      text: text.slice(range.start, range.end).replace(/\s+/g, ' '),
      gloss: undefined,
      sentence: sentenceAround(text, range.start, range.end - range.start),
      range,
    });
  }

  // 묶은 구를 시트에서 처리하고 닫으면 선택을 비우고, 묶기 모드를 열어 시작한 시트면 모드도 끄다(그러면 영상이 이전 상태로 돌아간다).
  function endPick() {
    setSel(null);
    if (fromPick.current) {
      fromPick.current = false;
      setPick(false);
    }
  }
  const picked = sel ? text.slice(sel.start, sel.end).replace(/\s+/g, ' ') : '';
  function savePicked(anchor: HTMLElement) {
    if (!sel) return;
    lastAnchor.current = anchor;
    fromPick.current = true;
    setActive({ kind: 'phrase', text: picked, sentence: sentenceAround(text, sel.start, sel.end - sel.start), anchor, range: sel });
  }

  return (
    <>
      {nodes}
      {learn && (
        <span lang="ko" className="mt-3 flex flex-wrap items-center gap-2 text-sm font-semibold">
          <button
            ref={pickToggle}
            type="button"
            aria-pressed={pick}
            onClick={() => {
              setPick((v) => !v);
              setSel(null);
            }}
            className={`flex min-h-11 items-center gap-1.5 rounded-full border-2 px-3 whitespace-nowrap ${
              pick ? 'border-marker bg-marker/20' : 'border-current/30 hover:bg-current/10'
            }`}
          >
            <Link2 size={16} aria-hidden />
            구로 묶기
          </button>
          {pick && !sel && <span className="font-normal opacity-80">이어진 단어를 차례로 탭하세요. 최대 {MAX_PHRASE_WORDS}단어예요.</span>}
          {sel && (
            <>
              <span lang="en" className="min-w-0 font-bold break-words">
                “{picked}”
              </span>
              <button
                type="button"
                onClick={(e) => savePicked(e.currentTarget)}
                className="min-h-11 rounded-full bg-marker px-4 whitespace-nowrap text-ink"
              >
                이 구 저장
              </button>
            </>
          )}
        </span>
      )}
      {active && (
        <WordPopover
          key={`${active.kind}:${active.text.toLowerCase()}`}
          kind={active.kind}
          text={active.text}
          gloss={active.gloss}
          sentence={active.sentence}
          source={source}
          anchor={active.anchor}
          extend={{
            before: !!extendRange(text, active.range, 'before'),
            after: !!extendRange(text, active.range, 'after'),
            onExtend: extend,
          }}
          onClose={() => {
            restoreFocus();
            setActive(null);
            endPick();
          }}
          onPronounce={(p) => {
            setActive(null);
            setPhrase(p);
          }}
        />
      )}
      {phrase && (
        <YouGlishSheet
          phrase={phrase}
          onClose={() => {
            const anchor = focusTarget();
            setPhrase(null);
            endPick();
            if (anchor?.isConnected) anchor.focus({ preventScroll: true });
          }}
        />
      )}
    </>
  );
}
