import { Check, Volume2, X } from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ReadglossOffError, lookupWord, saveWord, type WordInfo } from '../lib/api';
import { useWide } from './ui';

// 한 번 찾은 단어는 이 세션 동안 다시 묻지 않는다. 실패한 조회는 담지 않아 다시 누르면 재시도한다.
const cache = new Map<string, WordInfo>();

type Lookup =
  | { status: 'loading' }
  | { status: 'ready'; info: WordInfo }
  | { status: 'off'; message: string }
  | { status: 'error'; message: string };
type Saving = 'idle' | 'saving' | 'saved' | 'error';

const MARGIN = 12;

export function WordPopover({
  word,
  sentence,
  anchor,
  onClose,
  onPronounce,
}: {
  word: string;
  sentence: string;
  anchor: HTMLElement;
  onClose: () => void;
  onPronounce: (phrase: string) => void;
}) {
  const wide = useWide();
  const key = word.toLowerCase();
  const [lookup, setLookup] = useState<Lookup>(() => {
    const hit = cache.get(key);
    return hit ? { status: 'ready', info: hit } : { status: 'loading' };
  });
  const [saving, setSaving] = useState<Saving>('idle');
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const closeNow = useRef(onClose);
  closeNow.current = onClose;

  useEffect(() => {
    if (cache.has(key)) return;
    const controller = new AbortController();
    lookupWord(word, controller.signal).then(
      (info) => {
        cache.set(key, info);
        setLookup({ status: 'ready', info });
      },
      (e: unknown) => {
        if (controller.signal.aborted) return;
        const message = e instanceof Error ? e.message : '뜻을 찾지 못했어요.';
        setLookup(e instanceof ReadglossOffError ? { status: 'off', message } : { status: 'error', message });
      },
    );
    return () => controller.abort();
  }, [key, word]);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeNow.current();
    };
    const onPointer = (e: PointerEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) closeNow.current();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  // 폰에서는 아래 시트가 화면을 덮으므로 뒤쪽 스크롤을 잠근다.
  useEffect(() => {
    if (wide) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [wide]);

  // 넓은 화면: 눌린 단어 아래(공간이 모자라면 위)에 놓고 화면 안으로 가둔다. 자막이 밀려 단어가 화면 밖으로 나가면 닫는다.
  useLayoutEffect(() => {
    if (!wide) return;
    const place = () => {
      const panel = panelRef.current;
      if (!panel) return;
      if (!anchor.isConnected) return closeNow.current();
      const rect = anchor.getClientRects()[0] ?? anchor.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight) return closeNow.current();
      const { offsetWidth: w, offsetHeight: h } = panel;
      const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - w - MARGIN));
      const below = rect.bottom + 8;
      const top = below + h + MARGIN <= window.innerHeight ? below : Math.max(MARGIN, rect.top - 8 - h);
      setPos((p) => (p && p.top === top && p.left === left ? p : { top, left }));
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [wide, anchor, lookup, saving]);

  const info = lookup.status === 'ready' ? lookup.info : null;
  const lemma = info?.lemma || key;
  const senses = info ? info.senses.filter((s) => s !== info.gloss) : [];

  async function save() {
    if (!info || saving === 'saving' || saving === 'saved') return;
    setSaving('saving');
    try {
      await saveWord({ word, lemma: info.lemma, gloss: info.gloss, sentence });
      setSaving('saved');
    } catch (e) {
      setSaving(e instanceof ReadglossOffError ? 'idle' : 'error');
      if (e instanceof ReadglossOffError) setLookup({ status: 'off', message: e.message });
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = panelRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)');
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      data-word-popover
      aria-modal={wide ? undefined : true}
      aria-label={`${word} 뜻`}
      onKeyDown={onKeyDown}
      style={wide ? { top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? 'visible' : 'hidden' } : undefined}
      className={
        wide
          ? 'fixed z-40 max-h-[min(70dvh,560px)] w-80 overflow-y-auto rounded-2xl border border-line bg-surface p-4 shadow-[0_12px_32px_-12px_rgb(20_33_61/0.35)]'
          : 'relative max-h-[85dvh] w-full max-w-[480px] overflow-y-auto rounded-t-3xl bg-surface px-5 pt-5 pb-[calc(20px+env(safe-area-inset-bottom))]'
      }
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p lang="en" className="text-xl leading-snug font-bold break-words">
            {lemma}
          </p>
          {key !== lemma && (
            <p lang="en" className="text-sm text-ink-soft">
              눌러 본 말: {word}
            </p>
          )}
        </div>
        {info?.pos && <span className="mt-1 shrink-0 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">{info.pos}</span>}
        <button
          ref={closeRef}
          type="button"
          onClick={onClose}
          aria-label="닫기"
          className="-mt-2 -mr-2 grid size-11 shrink-0 place-items-center rounded-full text-ink hover:bg-line/60"
        >
          <X size={22} aria-hidden />
        </button>
      </div>

      <div className="mt-2 min-h-12" aria-live="polite">
        {lookup.status === 'loading' && <p className="text-ink-soft">뜻을 찾는 중이에요.</p>}
        {(lookup.status === 'off' || lookup.status === 'error') && (
          <p className={lookup.status === 'off' ? 'leading-relaxed text-ink-soft' : 'leading-relaxed text-end-press'}>{lookup.message}</p>
        )}
        {info && !info.gloss && senses.length === 0 && <p className="leading-relaxed text-ink-soft">사전에서 뜻을 찾지 못했어요.</p>}
        {info?.gloss && (
          <p className="text-lg font-semibold">
            <span className="mark">{info.gloss}</span>
          </p>
        )}
        {senses.length > 0 && (
          <ul className="mt-2 space-y-1 text-[15px] leading-relaxed text-ink-soft">
            {senses.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onPronounce(lemma)}
          className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full border border-line bg-surface px-4 text-sm font-semibold whitespace-nowrap text-ink hover:bg-paper"
        >
          <Volume2 size={18} aria-hidden />
          발음 듣기
        </button>
        {lookup.status !== 'off' && (
          <button
            type="button"
            onClick={save}
            disabled={!info || saving === 'saving' || saving === 'saved'}
            className="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-full bg-ink px-4 text-sm font-semibold whitespace-nowrap text-white disabled:bg-ink-soft/40"
          >
            {saving === 'saved' && <Check size={18} aria-hidden />}
            {saving === 'saved' ? '저장했어요' : saving === 'saving' ? '저장하는 중…' : '단어장에 저장'}
          </button>
        )}
      </div>
      {saving === 'error' && (
        <p role="alert" className="mt-2 text-sm text-end-press">
          저장하지 못했어요. 다시 눌러 주세요.
        </p>
      )}
    </div>
  );

  return createPortal(
    wide ? (
      panel
    ) : (
      <div className="fixed inset-0 z-40 flex items-end justify-center">
        <div className="absolute inset-0 bg-ink/40" aria-hidden />
        {panel}
      </div>
    ),
    document.body,
  );
}
