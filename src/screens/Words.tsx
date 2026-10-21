import { Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { WordPopover } from '../components/WordPopover';
import { YouGlishSheet } from '../components/YouGlishSheet';
import { List, Screen } from '../components/ui';
import { ReadglossOffError } from '../lib/api';
import { WORD_STATUS_LABEL, filterWordbook, getWordbookData, type WordbookData, type WordbookPhrase, type WordbookWord } from '../lib/apiWords';

type Tab = 'words' | 'phrases';
type Load = { status: 'loading' } | { status: 'off' } | { status: 'error'; message: string } | { status: 'ready'; data: WordbookData };
type Open = { kind: 'word' | 'phrase'; text: string; gloss: string; anchor: HTMLElement };

function dayLabel(ts: number): string {
  return ts > 0 ? new Date(ts).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' }) : '';
}

function Row({ title, gloss, meta, chip, onOpen }: { title: string; gloss: string; meta: string; chip?: string; onOpen: (anchor: HTMLElement) => void }) {
  return (
    <button
      type="button"
      onClick={(e) => onOpen(e.currentTarget)}
      aria-haspopup="dialog"
      className="flex min-h-16 w-full items-center gap-3 px-4 py-3 text-left hover:bg-paper"
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
  );
}

export function Words() {
  const [tab, setTab] = useState<Tab>('words');
  const [query, setQuery] = useState('');
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [open, setOpen] = useState<Open | null>(null);
  const [pronounce, setPronounce] = useState<string | null>(null);

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
                      />
                    ))
                  : phrases.map((p) => (
                      <Row key={p.id} title={p.text} gloss={p.gloss} meta={dayLabel(p.ts)} onOpen={(anchor) => setOpen({ kind: 'phrase', text: p.text, gloss: p.gloss, anchor })} />
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
      {pronounce && <YouGlishSheet phrase={pronounce} onClose={() => setPronounce(null)} />}
    </Screen>
  );
}
