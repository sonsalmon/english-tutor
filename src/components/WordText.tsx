import { useRef, useState, type ReactNode } from 'react';
import { WordPopover } from './WordPopover';
import { YouGlishSheet } from './YouGlishSheet';

const TOKEN = /[A-Za-z][A-Za-z'’-]*/g;
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

function lookupForm(token: string): string | null {
  const word = token.replace(/’/g, "'").replace(/[-']+$/, '');
  return word.length >= 2 && word.length <= 64 ? word : null;
}

type Active = { word: string; sentence: string; anchor: HTMLElement };

export function WordText({ text }: { text: string }) {
  const [active, setActive] = useState<Active | null>(null);
  const [phrase, setPhrase] = useState<string | null>(null);
  const lastAnchor = useRef<HTMLElement | null>(null);

  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const m of text.matchAll(TOKEN)) {
    const word = lookupForm(m[0]);
    if (!word) continue;
    if (m.index > cursor) nodes.push(text.slice(cursor, m.index));
    const sentence = sentenceAround(text, m.index, m[0].length);
    nodes.push(
      <button
        key={m.index}
        type="button"
        lang="en"
        data-word
        aria-haspopup="dialog"
        onClick={(e) => {
          e.stopPropagation();
          lastAnchor.current = e.currentTarget;
          setActive({ word, sentence, anchor: e.currentTarget });
        }}
        className="pointer-events-auto inline cursor-pointer rounded-sm text-left underline-offset-4 hover:underline hover:decoration-dotted"
      >
        {m[0]}
      </button>,
    );
    cursor = m.index + m[0].length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));

  function restoreFocus() {
    const anchor = lastAnchor.current;
    if (anchor?.isConnected && document.activeElement?.closest('[data-word-popover]')) anchor.focus({ preventScroll: true });
  }

  return (
    <>
      {nodes}
      {active && (
        <WordPopover
          word={active.word}
          sentence={active.sentence}
          anchor={active.anchor}
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
