import { ChevronDown } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { FeedPlayer } from '../components/FeedPlayer';
import { StarButton } from '../components/StarButton';
import { WordText } from '../components/WordText';
import { getFeed, loadSeen, rememberSeen, reportBlockedVideo, saveSeen, type FeedClip, type FeedFilter, type NativeInfo } from '../lib/apiFeed';

type Load = { status: 'loading' | 'ready' | 'off' | 'error'; message?: string };

const reducedMotion = (): boolean => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const KIND_LABEL: Record<string, string> = { idiom: '관용구', phrasal_verb: '구동사', chunk: '고정 표현', discourse_marker: '담화 표지' };
const REGISTER_LABEL: Record<string, string> = { casual: '편한 말', neutral: '보통', work: '일하는 자리' };
const SOURCE_LABEL: Record<FeedClip['source'], string> = { mine: '내 표현', browse: '둘러보기', native: '원어민 표현' };

function NativePanel({ info }: { info: NativeInfo }) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label="원어민 표현 설명" className="rounded-xl bg-white/10 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 lang="en" className="text-xl leading-tight font-bold break-words">
          {info.expression}
        </h2>
        {KIND_LABEL[info.kind] && <span className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs font-semibold">{KIND_LABEL[info.kind]}</span>}
      </div>
      <p className="mt-1 text-base font-semibold">{info.meaning_ko}</p>
      {info.why_hard && <p className="mt-1 text-sm leading-snug text-white/80">{info.why_hard}</p>}
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="mt-1 flex min-h-11 min-w-11 items-center gap-1 text-sm font-semibold underline underline-offset-2"
      >
        {open ? '접기' : '자세히'}
      </button>
      {open && (
        <dl className="mt-1 grid gap-1 text-sm text-white/80">
          {info.example && (
            <div>
              <dt className="font-semibold text-white">예문</dt>
              <dd lang="en">{info.example}</dd>
            </div>
          )}
          <div>
            <dt className="font-semibold text-white">원어민 빈도</dt>
            <dd>백만 낱말당 {Math.round(info.per_million)}번</dd>
          </div>
          {REGISTER_LABEL[info.register] && (
            <div>
              <dt className="font-semibold text-white">쓰는 자리</dt>
              <dd>{REGISTER_LABEL[info.register]}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  );
}

function Card({ clip, index, count, active, last, loadingMore, onNext, onBlocked }: { clip: FeedClip; index: number; count: number; active: boolean; last: boolean; loadingMore: boolean; onNext: () => void; onBlocked: () => void }) {
  const units = clip.term && clip.term.trim().split(/\s+/).length >= 2 ? [{ text: clip.term }] : undefined;
  return (
    <article
      aria-posinset={index + 1}
      aria-setsize={count}
      aria-label={`클립 ${index + 1}`}
      className="relative flex h-full shrink-0 snap-start snap-always flex-col overflow-y-auto bg-ink px-5 pt-[4.75rem] pb-5 text-white"
    >
      <div className="flex min-h-[18rem] flex-1 flex-col justify-center gap-2">
        <FeedPlayer clip={clip} active={active} autoplay={!reducedMotion()} onBlocked={onBlocked} />
        <p className="truncate text-sm text-white/70">
          {clip.channel}
          {clip.channel && clip.title ? ' · ' : ''}
          {clip.title}
        </p>
      </div>
      {clip.native && <NativePanel info={clip.native} />}
      <p lang="en" className="py-4 text-[22px] leading-snug font-semibold break-words lg:text-2xl">
        <WordText text={clip.text} units={units} />
      </p>
      <div className="flex items-center gap-3">
        <span className="rounded-full bg-white/15 px-3 py-1.5 text-sm font-semibold">{SOURCE_LABEL[clip.source]}</span>
        <span className="flex-1" />
        <span className="rounded-full bg-white">
          <StarButton kind="phrase" text={clip.term ?? clip.text} gloss={clip.native?.meaning_ko ?? ''} />
        </span>
        <button
          type="button"
          onClick={onNext}
          aria-label={last && loadingMore ? '다음 클립을 불러오는 중' : '다음 클립'}
          disabled={last && !loadingMore}
          className="grid size-11 place-items-center rounded-full bg-white text-ink disabled:opacity-40"
        >
          <ChevronDown size={22} aria-hidden />
        </button>
      </div>
    </article>
  );
}

export function Feed() {
  const [filter, setFilter] = useState<FeedFilter>('mine');
  const [clips, setClips] = useState<FeedClip[]>([]);
  const [load, setLoad] = useState<Load>({ status: 'loading' });
  const [more, setMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [terms, setTerms] = useState(0);
  const [nativeCount, setNativeCount] = useState(0);
  const [index, setIndex] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  const clipsRef = useRef<FeedClip[]>([]);
  const seen = useRef<string[]>(loadSeen());
  const busy = useRef(false);
  const generation = useRef(0);

  const fetchPage = useCallback(
    async (append: boolean) => {
      if (busy.current) return;
      busy.current = true;
      const mine = generation.current;
      if (append) setLoadingMore(true);
      try {
        const exclude = [...seen.current, ...clipsRef.current.map((c) => c.id)];
        const page = await getFeed(filter, exclude);
        if (mine !== generation.current) return;
        if (!page.available) {
          setLoad({ status: 'off' });
          return;
        }
        const have = new Set(clipsRef.current.map((c) => c.id));
        const fresh = page.clips.filter((c) => !have.has(c.id));
        clipsRef.current = [...clipsRef.current, ...fresh];
        setClips(clipsRef.current);
        setTerms(page.terms);
        setNativeCount(page.native);
        setMore(fresh.length > 0);
        setLoad({ status: 'ready' });
      } catch (e) {
        if (mine !== generation.current) return;
        if (!append) setLoad({ status: 'error', message: e instanceof Error ? e.message : '클립을 불러오지 못했어요.' });
        else setMore(false);
      } finally {
        busy.current = false;
        if (append) setLoadingMore(false);
      }
    },
    [filter],
  );

  useEffect(() => {
    generation.current += 1;
    busy.current = false;
    clipsRef.current = [];
    setClips([]);
    setIndex(0);
    setMore(true);
    setLoad({ status: 'loading' });
    scroller.current?.scrollTo({ top: 0 });
    void fetchPage(false);
  }, [fetchPage]);

  // 본 클립은 기억해서 다음에 다시 나오지 않게 하고, 끝에 가까워지면 다음 묶음을 미리 받는다.
  useEffect(() => {
    const current = clips[index];
    if (current) {
      seen.current = rememberSeen(seen.current, [current.id]);
      saveSeen(seen.current);
    }
    if (more && !busy.current && clips.length > 0 && index >= clips.length - 2) void fetchPage(true);
  }, [index, clips, more, fetchPage]);

  const goTo = useCallback((next: number) => {
    const el = scroller.current;
    if (!el || next < 0) return;
    el.scrollTo({ top: next * el.clientHeight, behavior: reducedMotion() ? 'auto' : 'smooth' });
  }, []);

  // 재생 오류가 난 영상은 서버에 알리고(다음부터 빠진다) 다음 카드로 넘긴다. 마지막 카드면 다음 묶음이 오는 대로 넘긴다.
  const pendingAdvance = useRef<number | null>(null);
  const onBlocked = useCallback(
    (clip: FeedClip, at: number) => {
      void reportBlockedVideo(clip.video_id);
      if (at + 1 < clipsRef.current.length) goTo(at + 1);
      else pendingAdvance.current = at;
    },
    [goTo],
  );
  useEffect(() => {
    const at = pendingAdvance.current;
    if (at !== null && clips.length > at + 1) {
      pendingAdvance.current = null;
      goTo(at + 1);
    }
  }, [clips, goTo]);

  const frame = useRef(0);
  const onScroll = () => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const el = scroller.current;
      if (el && el.clientHeight > 0) setIndex(Math.round(el.scrollTop / el.clientHeight));
    });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'ArrowDown' || e.key === 'PageDown') {
      e.preventDefault();
      goTo(Math.min(index + 1, clips.length - 1));
    } else if (e.key === 'ArrowUp' || e.key === 'PageUp') {
      e.preventDefault();
      goTo(Math.max(index - 1, 0));
    }
  };

  const chip = (id: FeedFilter, label: string) => (
    <button
      key={id}
      type="button"
      role="tab"
      aria-selected={filter === id}
      onClick={() => setFilter(id)}
      className={`min-h-11 rounded-full px-4 text-sm font-semibold ${filter === id ? 'bg-white text-ink' : 'bg-black/50 text-white'}`}
    >
      {label}
    </button>
  );

  // 보여 드릴 새 클립이 없는 이유가 '이미 다 봤어요'인지(목록은 있음) 확인해, 다 봤을 때만 처음부터 다시 보기를 보인다.
  const exhausted = load.status === 'ready' && clips.length === 0 && (filter !== 'native' || nativeCount > 0);
  const resetSeen = () => {
    seen.current = [];
    saveSeen([]);
    setLoad({ status: 'loading' });
    void fetchPage(false);
  };

  const message =
    load.status === 'loading'
      ? '클립을 찾는 중이에요.'
      : load.status === 'off'
        ? '자막 데이터베이스를 찾지 못해서 클립을 보여 드릴 수 없어요.'
        : load.status === 'error'
          ? load.message
          : clips.length === 0
            ? filter === 'native' && nativeCount === 0
              ? '원어민 표현 목록이 아직 없어요.'
              : '새로 보여 드릴 클립이 더 없어요.'
            : null;

  return (
    <main className="relative mx-auto h-[calc(100dvh-4rem-env(safe-area-inset-bottom))] w-full max-w-[480px] overflow-hidden bg-ink lg:h-dvh lg:max-w-[calc(100dvh*9/16)]">
      <h1 className="sr-only">클립</h1>
      <div role="tablist" aria-label="클립 종류" className="absolute top-3 left-5 z-10 flex gap-2">
        {chip('mine', '내 표현')}
        {chip('browse', '둘러보기')}
        {chip('native', '원어민 표현')}
      </div>
      {filter === 'mine' && load.status === 'ready' && terms === 0 && (
        <p className="absolute top-[3.75rem] right-5 left-5 z-10 text-xs text-white/70">저장한 표현이 아직 없어서 둘러보기 장면으로 채웠어요.</p>
      )}

      {message ? (
        <div role={load.status === 'error' ? 'alert' : 'status'} className="flex h-full flex-col items-center justify-center gap-4 px-8 text-center text-white">
          <p className={load.status === 'loading' ? 'animate-pulse' : ''}>{message}</p>
          {load.status === 'error' && (
            <button type="button" onClick={() => void fetchPage(false)} className="min-h-11 rounded-full bg-white px-5 font-semibold text-ink">
              다시 불러오기
            </button>
          )}
          {exhausted && (
            <button type="button" onClick={resetSeen} className="min-h-11 rounded-full bg-white px-5 font-semibold text-ink">
              처음부터 다시 보기
            </button>
          )}
        </div>
      ) : (
        <div
          ref={scroller}
          role="feed"
          aria-label="영어 표현 클립"
          tabIndex={0}
          onScroll={onScroll}
          onKeyDown={onKeyDown}
          className="h-full snap-y snap-mandatory overflow-y-auto overscroll-y-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          {clips.map((clip, i) => (
            <Card
              key={clip.id}
              clip={clip}
              index={i}
              count={clips.length}
              active={i === index}
              last={i === clips.length - 1}
              loadingMore={loadingMore}
              onNext={() => goTo(i + 1)}
              onBlocked={() => onBlocked(clip, i)}
            />
          ))}
        </div>
      )}
    </main>
  );
}
