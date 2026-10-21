import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { extendRange, findUnits, lookupForm, WORD_TOKEN, type Range, type Unit } from '../lib/units';
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

type Piece = { index: number; length: number; label: string; word?: string; unit?: Unit };

const UnitsContext = createContext<Unit[]>([]);

// 아래 WordText 전부에 같은 구 목록을 적용한다(한 화면의 여러 문장이 같은 목록을 쓸 때).
export const WordUnitsProvider = UnitsContext.Provider;

// units: 알려진 두 낱말 이상 표현(뜻이 있으면 함께). 문장에서 먼저 찾아 낱말 대신 하나의 버튼으로 만든다. 없으면 WordUnitsProvider의 목록을 쓴다.
// onOpenChange: 단어 시트나 발음 시트가 열리고 닫힐 때 알린다(재생기가 영상을 멈췄다 되돌리는 데 쓴다).
export function WordText({ text, units, onOpenChange }: { text: string; units?: Unit[]; onOpenChange?: (open: boolean) => void }) {
  const inherited = useContext(UnitsContext);
  const [active, setActive] = useState<Active | null>(null);
  const [phrase, setPhrase] = useState<string | null>(null);
  const lastAnchor = useRef<HTMLElement | null>(null);
  const open = active !== null || phrase !== null;
  const notify = useRef(onOpenChange);
  notify.current = onOpenChange;
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current === open) return;
    wasOpen.current = open;
    notify.current?.(open);
  }, [open]);

  const matches = findUnits(text, units ?? inherited);
  const pieces: Piece[] = matches.map((m) => ({ index: m.index, length: m.length, label: text.slice(m.index, m.index + m.length), unit: m.unit }));
  for (const m of text.matchAll(WORD_TOKEN)) {
    const word = lookupForm(m[0]);
    if (!word || matches.some((u) => m.index >= u.index && m.index < u.index + u.length)) continue;
    pieces.push({ index: m.index, length: m[0].length, label: m[0], word });
  }
  pieces.sort((a, b) => a.index - b.index);

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const p of pieces) {
    if (p.index > cursor) nodes.push(text.slice(cursor, p.index));
    const range = { start: p.index, end: p.index + p.length };
    const sentence = sentenceAround(text, p.index, p.length);
    const open = (anchor: HTMLElement) => {
      lastAnchor.current = anchor;
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
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          open(e.currentTarget);
        }}
        className={`pointer-events-auto inline cursor-pointer rounded-sm text-left underline-offset-4 ${
          p.unit ? 'underline decoration-dotted decoration-2' : 'hover:underline hover:decoration-dotted'
        }`}
      >
        {p.label}
      </button>,
    );
    cursor = p.index + p.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));

  function restoreFocus() {
    const anchor = lastAnchor.current;
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

  return (
    <>
      {nodes}
      {active && (
        <WordPopover
          key={`${active.kind}:${active.text.toLowerCase()}`}
          kind={active.kind}
          text={active.text}
          gloss={active.gloss}
          sentence={active.sentence}
          anchor={active.anchor}
          extend={{
            before: !!extendRange(text, active.range, 'before'),
            after: !!extendRange(text, active.range, 'after'),
            onExtend: extend,
          }}
          onClose={() => {
            restoreFocus();
            setActive(null);
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
            setPhrase(null);
            if (lastAnchor.current?.isConnected) lastAnchor.current.focus({ preventScroll: true });
          }}
        />
      )}
    </>
  );
}
