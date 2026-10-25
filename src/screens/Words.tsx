import { Search, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { WordPopover } from '../components/WordPopover';
import { YouGlishSheet } from '../components/YouGlishSheet';
import { List, Screen } from '../components/ui';
import { ReadglossOffError } from '../lib/api';
import { deleteWordbookItem, restoreWordbookItem, type WordbookKind, type WordbookSnapshot } from '../lib/apiWordsDelete';
import { WORD_STATUS_LABEL, filterWordbook, getWordbookData, type WordbookData, type WordbookPhrase, type WordbookWord } from '../lib/apiWords';

type Tab = 'words' | 'phrases';
type Load = { status: 'loading' } | { status: 'off' } | { status: 'error'; message: string } | { status: 'ready'; data: WordbookData };
type Pending = { kind: WordbookKind; key: string; title: string };
type Toast = { message: string; snapshot?: WordbookSnapshot; error?: boolean };
const UNDO_MS = 8000;
type Open = { kind: 'word' | 'phrase'; text: string; gloss: string; anchor: HTMLElement };

function dayLabel(ts: number): string {
  return ts > 0 ? new Date(ts).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' }) : '';
}

function Row({ title, gloss, meta, chip, onOpen, onDelete }: { title: string; gloss: string; meta: string; chip?: string; onOpen: (anchor: HTMLElement) => void; onDelete: () => void }) {
  return (
    <div className="flex items-center hover:bg-paper">
    <button
      type="button"
      onClick={(e) => onOpen(e.currentTarget)}
      aria-haspopup="dialog"
      className="flex min-h-16 min-w-0 flex-1 items-center gap-3 py-3 pr-2 pl-4 text-left"
    >
      <span className="min-w-0 flex-1">
        <span lang="en" className="block font-semibold break-words">
          {title}
        </span>
        <span className="mt-0.5 block text-sm break-words text-ink-soft">{gloss || '뜻이 아직 없어요'}</span>
      </span>
      <span className="flex shrink-0 flex-col items-end gap-1 text-xs text-ink-soft">
        {chip && <span className="rounded-full bg-paper px-2 py-0.5 font-semibold text-ink">{chip}</span>}
        {meta}
      </span>
    </button>
    <button
      type="button"
      onClick={onDelete}
      aria-label={`${title} 지우기`}
      className="mr-1 flex size-11 shrink-0 items-center justify-center rounded-full text-ink-soft hover:text-end-press"
    >
      <Trash2 size={18} aria-hidden />
    </button>
    </div>
  );
}

export function Words() {
  const [tab, setTab] = useState<Tab>('words');
  const [query, setQuery] = useState('');
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [open, setOpen] = useState<Open | null>(null);
  const [pronounce, setPronounce] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    getWordbookData(controller.signal).then(
      (data) => setLoad({ status: 'ready', data }),
      (e: unknown) => {
        if (controller.signal.aborted) return;
        setLoad(e instanceof ReadglossOffError ? { status: 'off' } : { status: 'error', message: e instanceof Error ? e.message : '단어장을 불러오지 못했어요.' });
      },
    );
    return () => controller.abort();
  }, []);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const showToast = useCallback((next: Toast) => {
    window.clearTimeout(toastTimer.current);
    setToast(next);
    toastTimer.current = window.setTimeout(() => setToast(null), next.snapshot ? UNDO_MS : 5000);
  }, []);

  const reload = useCallback(async () => {
    try {
      setLoad({ status: 'ready', data: await getWordbookData() });
    } catch (e) {
      setLoad({ status: 'error', message: e instanceof Error ? e.message : '단어장을 불러오지 못했어요.' });
    }
  }, []);

  const confirmDelete = async () => {
    if (!pending || busy) return;
    const target = pending;
    setBusy(true);
    try {
      const snapshot = await deleteWordbookItem(target.kind, target.key);
      setLoad((cur) =>
        cur.status === 'ready'
          ? {
              status: 'ready',
              data: {
                words: target.kind === 'word' ? cur.data.words.filter((w) => w.lemma !== target.key) : cur.data.words,
                phrases: target.kind === 'phrase' ? cur.data.phrases.filter((p) => p.id !== target.key) : cur.data.phrases,
              },
            }
          : cur,
      );
      showToast({ message: `"${target.title}"을(를) 지웠어요.`, snapshot });
    } catch (e) {
      showToast({ message: e instanceof Error ? e.message : '지우지 못했어요.', error: true });
    } finally {
      setBusy(false);
      setPending(null);
    }
  };

  const undo = async () => {
    const snapshot = toast?.snapshot;
    if (!snapshot) return;
    window.clearTimeout(toastTimer.current);
    setToast(null);
    try {
      await restoreWordbookItem(snapshot);
      await reload();
      showToast({ message: '되돌렸어요.' });
    } catch (e) {
      showToast({ message: e instanceof Error ? e.message : '되돌리지 못했어요.', error: true });
    }
  };

  const data = load.status === 'ready' ? load.data : null;
  const words = useMemo(() => filterWordbook<WordbookWord>(data?.words ?? [], query, (w) => `${w.word} ${w.lemma}`), [data, query]);
  const phrases = useMemo(() => filterWordbook<WordbookPhrase>(data?.phrases ?? [], query, (p) => p.text), [data, query]);
  const shown = tab === 'words' ? words : phrases;
  const total = tab === 'words' ? data?.words.length ?? 0 : data?.phrases.length ?? 0;

  const tabButton = (id: Tab, label: string, count: number) => (
    <button
      key={id}
      type="button"
      role="tab"
      aria-selected={tab === id}
      onClick={() => setTab(id)}
      className={`min-h-11 flex-1 rounded-full px-4 text-sm font-semibold ${tab === id ? 'bg-ink text-white' : 'text-ink hover:bg-paper'}`}
    >
      {label} {count > 0 && <span className={tab === id ? 'text-white/80' : 'text-ink-soft'}>{count}</span>}
    </button>
  );

  return (
    <Screen wide>
      <header className="flex h-11 items-center lg:mb-4 lg:h-auto">
        <h1 className="text-[28px] font-bold">단어장</h1>
      </header>

      {load.status === 'loading' && (
        <p role="status" className="mt-6 text-ink-soft">
          단어장을 불러오는 중이에요.
        </p>
      )}

      {load.status === 'off' && (
        <div role="status" className="mt-6 rounded-2xl border border-line bg-surface p-5">
          <p className="font-bold">readgloss 꺼짐</p>
          <p className="mt-1 leading-relaxed text-ink-soft">
            단어장은 읽기 확장 프로그램(readgloss)에 저장돼요. 지금은 연결이 안 돼서 목록을 못 보여 드려요. 확장 프로그램을 켜면 이곳에 단어와 저장한 문장이 모여요.
          </p>
        </div>
      )}

      {load.status === 'error' && (
        <p role="alert" className="mt-6 text-end-press">
          {load.message}
        </p>
      )}

      {data && (
        <>
          <div role="tablist" aria-label="단어장 종류" className="mt-4 flex gap-1 rounded-full border border-line bg-surface p-1 lg:max-w-sm">
            {tabButton('words', '단어', data.words.length)}
            {tabButton('phrases', '문장', data.phrases.length)}
          </div>

          <label className="relative mt-3 block lg:max-w-sm">
            <span className="sr-only">단어장 검색</span>
            <Search size={18} aria-hidden className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="영어나 뜻으로 찾기"
              className="min-h-11 w-full rounded-full border border-line bg-surface pr-4 pl-11 text-base"
            />
          </label>

          <div className="mt-4" role="tabpanel">
            {shown.length === 0 ? (
              <p className="leading-relaxed text-ink-soft">
                {total === 0
                  ? tab === 'words'
                    ? '아직 저장한 단어가 없어요. 읽다가 단어를 찾아보거나 별을 누르면 여기에 모여요.'
                    : '아직 저장한 문장이 없어요. 표현에서 별을 누르면 여기에 모여요.'
                  : '찾는 항목이 없어요.'}
              </p>
            ) : (
              <List columns={2}>
                {tab === 'words'
                  ? words.map((w) => (
                      <Row
                        key={w.lemma}
                        title={w.word}
                        gloss={w.gloss}
                        meta={dayLabel(w.ts)}
                        chip={w.status === 'learning' ? undefined : WORD_STATUS_LABEL[w.status]}
                        onOpen={(anchor) => setOpen({ kind: 'word', text: w.lemma, gloss: w.gloss, anchor })}
                        onDelete={() => setPending({ kind: 'word', key: w.lemma, title: w.word })}
                      />
                    ))
                  : phrases.map((p) => (
                      <Row
                        key={p.id}
                        title={p.text}
                        gloss={p.gloss}
                        meta={dayLabel(p.ts)}
                        onOpen={(anchor) => setOpen({ kind: 'phrase', text: p.text, gloss: p.gloss, anchor })}
                        onDelete={() => setPending({ kind: 'phrase', key: p.id, title: p.text })}
                      />
                    ))}
              </List>
            )}
          </div>
        </>
      )}

      {open && (
        <WordPopover
          key={`${open.kind}:${open.text}`}
          kind={open.kind}
          text={open.text}
          gloss={open.kind === 'phrase' ? open.gloss : undefined}
          sentence=""
          anchor={open.anchor}
          onClose={() => {
            if (open.anchor.isConnected) open.anchor.focus({ preventScroll: true });
            setOpen(null);
          }}
          onPronounce={(p) => {
            setOpen(null);
            setPronounce(p);
          }}
        />
      )}
      {pending && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-4 sm:items-center" onClick={() => !busy && setPending(null)}>
          <div
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="del-title"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.key === 'Escape' && !busy && setPending(null)}
            className="w-full max-w-sm rounded-2xl bg-surface p-5 shadow-lg"
          >
            <p id="del-title" className="font-bold">
              {pending.kind === 'word' ? '이 단어를 지울까요?' : '이 문장을 지울까요?'}
            </p>
            <p lang="en" className="mt-1 break-words text-ink-soft">
              {pending.title}
            </p>
            <p className="mt-2 text-sm text-ink-soft">단어장에서 없어져요. 지운 뒤 잠깐 동안은 되돌릴 수 있어요.</p>
            <div className="mt-4 flex gap-2">
              <button type="button" autoFocus onClick={() => setPending(null)} disabled={busy} className="min-h-11 flex-1 rounded-full border border-line font-semibold">
                취소
              </button>
              <button type="button" onClick={confirmDelete} disabled={busy} className="min-h-11 flex-1 rounded-full bg-end font-semibold text-white disabled:opacity-60">
                {busy ? '지우는 중' : '지우기'}
              </button>
            </div>
          </div>
        </div>
      )}
      {toast && (
        <div role="status" className="fixed inset-x-4 bottom-24 z-50 mx-auto flex max-w-sm items-center gap-3 rounded-2xl bg-ink px-4 py-3 text-white shadow-lg">
          <span className={`min-w-0 flex-1 break-words text-sm ${toast.error ? 'text-marker' : ''}`}>{toast.message}</span>
          {toast.snapshot && (
            <button type="button" onClick={undo} className="min-h-11 shrink-0 rounded-full px-3 font-bold text-marker">
              되돌리기
            </button>
          )}
        </div>
      )}
      {pronounce && <YouGlishSheet phrase={pronounce} onClose={() => setPronounce(null)} />}
    </Screen>
  );
}
