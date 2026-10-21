import { Captions, ChevronLeft, ChevronRight, ExternalLink, Keyboard, Pause, Play, RotateCcw, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { CaptionSheet, CHIP, CHIP_OFF, CHIP_ON, ENG_LABEL, SIZE_LABEL, SyncControl } from '../components/CaptionSheet';
import { mmss } from '../components/ClipPlayer';
import { rememberBlocked } from '../components/ClipList';
import { KoLine } from '../components/KoLine';
import { WordText } from '../components/WordText';
import { getClipSegments, type ClipLine, type ClipSegments } from '../lib/api';
import { lineFill, loadSync, saveSync, shiftLines, stepSync } from '../lib/captionTune';
import { canAutoScroll, lineSource, mergeSegments } from '../lib/clipLines';
import { closeClip, parseClipParam, type ClipTarget } from '../lib/clipRoute';
import { loadPrefs, nextEngMode, nextRepeat, nextTextSize, savePrefs, stepRate, visibleRates, type EngMode, type TextSize } from '../lib/playerPrefs';
import { KO_MODE_LABEL, loadKoSettings, nextKoMode, saveKoSettings } from '../lib/koLines';
import { REPEAT_TIMES, type RepeatMode } from '../lib/playerMachine';
import { keyCommand, SHORTCUTS } from '../lib/studyKeys';
import { useKoLines } from '../lib/useKoLines';
import { usePlayer } from '../lib/usePlayer';

const MORE_AT_OFFSET_S = 85;
const AUTO_SCROLL_PAUSE_MS = 3000;

type Loaded = { status: 'loading' } | { status: 'ok'; data: ClipSegments } | { status: 'missing' };

const BTN = 'flex min-h-12 items-center justify-center gap-1 rounded-full border px-2 text-sm font-semibold whitespace-nowrap disabled:opacity-40';
const BTN_PLAIN = 'border-surface/30 bg-surface/10 text-surface hover:bg-surface/20';
const BTN_PRIMARY = 'border-marker bg-marker text-ink';

// 글자 크기별 현재 줄 글자. Tailwind가 클래스를 찾도록 글자 그대로 적는다.
const SIZE_CLASS: Record<TextSize, string> = { sm: 'text-lg', md: 'text-xl', lg: 'text-2xl' };

function repeatLabel(repeat: RepeatMode, pass: number): string {
  if (repeat === 'x3') return `반복 ×${REPEAT_TIMES} · ${Math.min(pass, REPEAT_TIMES)}/${REPEAT_TIMES}`;
  if (repeat === 'inf') return `반복 무한 · ${pass}회`;
  return '반복 끔';
}

function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="hidden rounded border border-surface/30 px-1 font-mono text-xs text-surface/70 lg:inline">{children}</kbd>;
}

function watchUrl(videoId: string, t: number): string {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}&t=${Math.floor(t)}s`;
}

// 지금 줄 안에서 영상이 어디쯤인지 보이는 가는 막대. 100ms마다 플레이어 시각을 읽는다(화면 전체를 다시 그리지 않으려고 이 안에서만 갱신).
function LineProgress({ line, labels, getTime }: { line: ClipLine; labels: ClipLine; getTime: () => number | null }) {
  const [time, setTime] = useState(line.start);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const t = getTime();
      if (t !== null) setTime(t);
    }, 100);
    return () => window.clearInterval(timer);
  }, [getTime, line.id]);
  const span = Math.max(0.1, line.end - line.start);
  const ratio = Math.min(1, Math.max(0, (time - line.start) / span));
  return (
    <div aria-hidden className="mt-3 flex items-center gap-3 text-xs tabular-nums text-surface/70">
      <span>{mmss(labels.start)}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface/20">
        <div className="h-full bg-marker" style={{ width: `${ratio * 100}%` }} />
      </div>
      <span>{mmss(labels.end)}</span>
    </div>
  );
}

function Study({ target }: { target: ClipTarget }) {
  const { videoId, t } = target;
  const [loaded, setLoaded] = useState<Loaded>({ status: 'loading' });
  const [prefs] = useState(loadPrefs);
  const [eng, setEng] = useState<EngMode>(prefs.engMode);
  const [size, setSize] = useState<TextSize>(prefs.textSize);
  const [syncMs, setSyncMs] = useState(() => loadSync(videoId));
  const [ccOpen, setCcOpen] = useState(false);
  const ccButton = useRef<HTMLButtonElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const currentId = useRef<number | null>(null);
  const [ko, setKo] = useState(loadKoSettings);
  const [revealedId, setRevealedId] = useState<number | null>(null);
  const [help, setHelp] = useState(false);
  const [moreBusy, setMoreBusy] = useState<'before' | 'after' | null>(null);
  const [moreFailed, setMoreFailed] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const lastUserScroll = useRef(Number.NEGATIVE_INFINITY);

  useEffect(() => {
    const controller = new AbortController();
    getClipSegments(videoId, t, controller.signal).then(
      (data) => setLoaded(data.lines.length ? { status: 'ok', data } : { status: 'missing' }),
      () => {
        if (!controller.signal.aborted) setLoaded({ status: 'missing' });
      },
    );
    return () => controller.abort();
  }, [videoId, t]);

  const data = loaded.status === 'ok' ? loaded.data : null;
  const withLines = data !== null;
  const shifted = useMemo(() => (data ? { ...data, lines: shiftLines(data.lines, syncMs), atId: currentId.current ?? data.atId } : null), [data, syncMs]);
  const { mountRef, status, slow, state, rates, act } = usePlayer({
    videoId,
    title: data?.title ?? '',
    startTime: t,
    segments: shifted,
    nativeControls: !withLines,
    enabled: loaded.status !== 'loading',
    onBlocked: rememberBlocked,
    settings: prefs,
  });
  const ready = status === 'ready';
  const blocked = status === 'blocked';
  const line = withLines && state.index >= 0 ? state.lines[state.index] : null;
  const visible = visibleRates(rates);
  const lastIndex = state.lines.length - 1;
  const atEnd = state.held && state.index === lastIndex && !data?.hasMoreAfter;
  const masked = eng !== 'show' && line !== null && revealedId !== line.id;
  const koLine = useKoLines(videoId, state.lines, state.index, ko);

  useEffect(() => {
    saveKoSettings(ko);
  }, [ko]);

  useEffect(() => {
    savePrefs({ rate: state.rate, repeat: state.repeat, autoPause: state.autoPause, engMode: eng, textSize: size });
  }, [state.rate, state.repeat, state.autoPause, eng, size]);

  useEffect(() => {
    saveSync(videoId, syncMs);
  }, [videoId, syncMs]);

  // 형광펜: 현재 줄 카드의 채움 비율(--fill)을 100ms마다 DOM에 직접 써 화면 전체를 다시 그리지 않는다.
  useEffect(() => {
    const el = cardRef.current;
    if (!el || !line || masked) return;
    const paint = () => {
      const t = act.getTime();
      if (t !== null) el.style.setProperty('--fill', String(lineFill(line, t)));
    };
    paint();
    const timer = window.setInterval(paint, 100);
    return () => window.clearInterval(timer);
  }, [act, line, masked]);

  useEffect(() => {
    const list = listRef.current;
    const item = list?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!list || !item || !canAutoScroll(performance.now(), lastUserScroll.current, AUTO_SCROLL_PAUSE_MS)) return;
    const top = item.offsetTop - (list.clientHeight - item.clientHeight) / 2;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    list.scrollTo({ top: Math.max(0, top), behavior: reduce ? 'auto' : 'smooth' });
  }, [state.index, state.lines.length]);

  currentId.current = line?.id ?? null;

  function loadMore(side: 'before' | 'after') {
    if (!data || moreBusy) return;
    const edge = side === 'before' ? data.lines[0] : data.lines[data.lines.length - 1];
    const at = Math.max(0, edge.start + (side === 'before' ? -MORE_AT_OFFSET_S : MORE_AT_OFFSET_S));
    setMoreBusy(side);
    setMoreFailed(false);
    getClipSegments(videoId, at).then(
      (next) => {
        setLoaded((prev) => (prev.status === 'ok' ? { status: 'ok', data: { ...mergeSegments(prev.data, next, side), atId: currentId.current ?? prev.data.atId } } : prev));
        setMoreBusy(null);
      },
      () => {
        setMoreFailed(true);
        setMoreBusy(null);
      },
    );
  }

  const latest = useRef({ state, visible, ready, eng, ko, help, withLines, syncMs });
  latest.current = { state, visible, ready, eng, ko, help, withLines, syncMs };
  useEffect(() => {
    const dialogOpen = () => document.querySelector('[role="dialog"]') !== null;
    const onKeyDown = (e: KeyboardEvent) => {
      if (dialogOpen()) return;
      const el = e.target as HTMLElement | null;
      const editable = !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
      const command = keyCommand(e, editable);
      if (!command) return;
      const cur = latest.current;
      if (command === 'help') setHelp((v) => !v);
      else if (command === 'close') (cur.help ? setHelp(false) : closeClip());
      else if (command === 'ko') {
        if (!cur.withLines || !cur.ko.enabled) return;
        setKo({ ...cur.ko, mode: nextKoMode(cur.ko.mode) });
      } else if (!cur.ready || !cur.withLines) return;
      else if (command === 'toggle') act.toggle();
      else if (command === 'prev') act.prev();
      else if (command === 'next') act.next();
      else if (command === 'replay') act.replay();
      else if (command === 'repeat') act.setRepeat(nextRepeat(cur.state.repeat));
      else if (command === 'autoPause') act.setAutoPause(!cur.state.autoPause);
      else if (command === 'slower') act.setRate(stepRate(cur.visible, cur.state.rate, -1));
      else if (command === 'faster') act.setRate(stepRate(cur.visible, cur.state.rate, 1));
      else if (command === 'eng') setEng(nextEngMode(cur.eng));
      else if (command === 'syncEarlier') setSyncMs(stepSync(cur.syncMs, -1));
      else if (command === 'syncLater') setSyncMs(stepSync(cur.syncMs, 1));
      e.preventDefault();
    };
    // Space로 누른 버튼이 keyup에서 한 번 더 눌리지 않게 한다.
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === ' ' && !dialogOpen()) e.preventDefault();
    };
    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    };
  }, [act]);

  const statusText = state.gapUntil !== null ? '잠깐 쉬었다가 다시 들려줘요.' : state.held ? '줄 끝에서 멈췄어요. 재생을 누르면 이어져요.' : '';

  return (
    <div
      className={`study relative flex h-dvh flex-col overflow-hidden bg-ink text-surface max-lg:[@media(max-height:700px)]:h-auto max-lg:[@media(max-height:700px)]:min-h-dvh max-lg:[@media(max-height:700px)]:overflow-visible`}
    >
      <header className="flex h-16 shrink-0 items-center gap-2 px-2 lg:px-6">
        <button
          type="button"
          onClick={closeClip}
          aria-label="닫기"
          className="flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-surface/15"
        >
          <X size={22} aria-hidden />
        </button>
        <h1 className="min-w-0 flex-1 truncate font-semibold">{data?.title || '클립 공부'}</h1>
        <a
          href={watchUrl(videoId, t)}
          target="_blank"
          rel="noopener noreferrer"
          className="hidden min-h-11 items-center gap-1.5 rounded-full px-3 text-sm text-surface/80 hover:bg-surface/15 lg:flex"
        >
          <ExternalLink size={16} aria-hidden />
          YouTube에서 보기
        </a>
        {withLines && !blocked && (
          <button
            ref={ccButton}
            type="button"
            onClick={() => setCcOpen(true)}
            aria-haspopup="dialog"
            aria-label="자막 설정"
            className="flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-surface/15 lg:hidden"
          >
            <Captions size={22} aria-hidden />
          </button>
        )}
        <button
          type="button"
          onClick={() => setHelp((v) => !v)}
          aria-expanded={help}
          aria-controls="study-shortcuts"
          className="hidden min-h-11 items-center gap-1.5 rounded-full px-3 text-sm text-surface/80 hover:bg-surface/15 lg:flex"
        >
          <Keyboard size={16} aria-hidden />
          단축키 <Kbd>?</Kbd>
        </button>
      </header>

      {help && (
        <section
          id="study-shortcuts"
          aria-label="단축키"
          className="absolute top-16 right-6 z-20 hidden w-80 rounded-2xl border border-surface/30 bg-ink p-4 shadow-2xl lg:block"
        >
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            {SHORTCUTS.map((s) => (
              <div key={s.keys} className="contents">
                <dt>
                  <kbd className="rounded border border-surface/30 px-1.5 font-mono text-xs">{s.keys}</kbd>
                </dt>
                <dd className="text-surface/80">{s.label}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      <div className={`flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[minmax(0,1fr)_25rem] lg:gap-6 lg:px-6 lg:pb-6 max-lg:[@media(max-height:700px)]:flex-none`}>
        <section className="shrink-0 px-3 lg:max-w-[50rem] lg:overflow-y-auto lg:px-0">
          {blocked ? (
            <div role="alert" className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-lg border border-surface/30 p-4 text-center">
              <p className="font-semibold">이 영상은 앱 안에서 틀 수 없어요.</p>
              <a
                href={watchUrl(videoId, t)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-surface px-4 text-sm font-semibold text-ink"
              >
                <ExternalLink size={18} aria-hidden />
                YouTube에서 보기 ({mmss(t)}부터)
              </a>
            </div>
          ) : (
            <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
              <div ref={mountRef} className={`absolute inset-0 [&_iframe]:size-full [&_iframe]:border-0 ${withLines ? '[&_iframe]:pointer-events-none' : ''}`} />
              {!ready && (
                <div role="status" aria-label="영상을 불러오는 중" className="absolute inset-0 flex items-center justify-center bg-black">
                  <img src={`https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/hqdefault.jpg`} alt="" className="absolute inset-0 size-full object-cover opacity-50" />
                  <span className="relative size-8 animate-spin rounded-full border-2 border-surface/40 border-t-surface" />
                </div>
              )}
              {withLines && ready && (
                <>
                  <button type="button" onClick={act.toggle} aria-label={state.playing ? '일시정지' : '재생'} className="absolute inset-0 cursor-pointer" />
                  {!state.playing && (
                    <span aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
                      <span className="flex size-[4.5rem] items-center justify-center rounded-full bg-ink/90 text-surface">
                        <Play size={26} fill="currentColor" />
                      </span>
                    </span>
                  )}
                </>
              )}
            </div>
          )}

          {loaded.status === 'missing' && !blocked && (
            <p role="status" className="mt-3 text-sm text-surface/80">
              줄 정보를 못 불러왔어요.
            </p>
          )}
          {slow && !blocked && (
            <p className="mt-2 text-sm">
              <a href={watchUrl(videoId, t)} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 underline">
                <ExternalLink size={16} aria-hidden />
                안 나오면 YouTube에서 보기 ({mmss(t)}부터)
              </a>
            </p>
          )}

          {withLines && !blocked && line && (
            <>
              <LineProgress line={line} labels={data.lines[state.index] ?? line} getTime={act.getTime} />
              <div ref={cardRef} className={`mt-3 rounded-2xl border-l-4 border-marker bg-surface/10 p-4 ${masked ? '' : 'line-fill'}`}>
                {masked ? (
                  <button
                    type="button"
                    onClick={() => setRevealedId(line.id)}
                    aria-label="영어 자막 보기"
                    className={`relative block min-h-14 w-full text-left ${SIZE_CLASS[size]} leading-snug font-semibold break-words`}
                  >
                    {eng === 'blur' ? (
                      <>
                        <span aria-hidden className="block blur-md select-none">
                          {line.text}
                        </span>
                        <span className="absolute inset-0 flex items-center justify-center">
                          <span className="rounded-full bg-ink/85 px-3 py-1 text-sm font-normal text-surface">탭하면 이 줄이 보여요.</span>
                        </span>
                      </>
                    ) : (
                      <span className="text-base font-normal text-surface/80">영어 자막이 숨겨져 있어요. 탭하면 보여요.</span>
                    )}
                  </button>
                ) : (
                  <p key={line.id} lang="en" className={`line-in min-h-14 ${SIZE_CLASS[size]} leading-snug font-semibold break-words`}>
                    <WordText text={line.text} onOpenChange={act.hold} source={lineSource(videoId, data?.title ?? '', line)} learn />
                  </p>
                )}
                <KoLine line={koLine} />
              </div>
              <p role="status" className="mt-2 flex min-h-11 items-center gap-3 text-sm text-surface/80">
                <span>{statusText}</span>
                {atEnd && (
                  <button type="button" onClick={() => act.jump(0)} className="min-h-11 rounded-full px-3 font-semibold underline">
                    처음부터
                  </button>
                )}
              </p>
              <div role="group" aria-label="줄 이동" className="grid grid-cols-[1fr_1fr_3.5rem_1fr] gap-2">
                <button type="button" onClick={act.prev} disabled={!ready || state.index <= 0} className={`${BTN} ${BTN_PLAIN}`}>
                  <ChevronLeft size={18} aria-hidden />
                  이전 줄
                </button>
                <button type="button" onClick={act.replay} disabled={!ready} className={`${BTN} ${BTN_PLAIN}`}>
                  <RotateCcw size={16} aria-hidden />
                  다시
                </button>
                <button
                  type="button"
                  onClick={act.toggle}
                  disabled={!ready}
                  aria-label={state.held ? '이어서 재생' : state.playing ? '일시정지' : '재생'}
                  className={`${BTN} ${state.held ? BTN_PRIMARY : BTN_PLAIN}`}
                >
                  {state.playing ? <Pause size={20} fill="currentColor" aria-hidden /> : <Play size={20} fill="currentColor" aria-hidden />}
                </button>
                <button type="button" onClick={act.next} disabled={!ready || state.index >= lastIndex} className={`${BTN} ${BTN_PLAIN}`}>
                  다음 줄
                  <ChevronRight size={18} aria-hidden />
                </button>
              </div>

              <div role="group" aria-label="재생 속도" className="mt-3 grid grid-cols-5 gap-2">
                {visible.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => act.setRate(r)}
                    aria-pressed={state.rate === r}
                    aria-label={`속도 ${r}배`}
                    disabled={!ready}
                    className={`${CHIP} px-0 ${state.rate === r ? CHIP_ON : CHIP_OFF}`}
                  >
                    {r}x
                  </button>
                ))}
              </div>
              {ready && !visible.includes(state.rate) && <p className="mt-2 text-sm text-surface/80">이 영상은 {state.rate}배를 지원하지 않아요.</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => act.setRepeat(nextRepeat(state.repeat))}
                  aria-pressed={state.repeat !== 'off'}
                  className={`${CHIP} ${state.repeat !== 'off' ? CHIP_ON : CHIP_OFF}`}
                >
                  {repeatLabel(state.repeat, state.pass)} <Kbd>R</Kbd>
                </button>
                <button
                  type="button"
                  onClick={() => act.setAutoPause(!state.autoPause)}
                  aria-pressed={state.autoPause}
                  className={`${CHIP} ${state.autoPause ? CHIP_ON : CHIP_OFF}`}
                >
                  줄마다 멈춤 {state.autoPause ? '켬' : '끔'} <Kbd>Q</Kbd>
                </button>
                <button
                  type="button"
                  onClick={() => setEng(nextEngMode(eng))}
                  aria-pressed={eng !== 'show'}
                  className={`${CHIP} ${eng !== 'show' ? CHIP_ON : CHIP_OFF}`}
                >
                  영어 자막 {ENG_LABEL[eng]} <Kbd>C</Kbd>
                </button>
                <div className="hidden items-center gap-2 lg:flex">
                  <button
                    type="button"
                    onClick={() => setSize(nextTextSize(size))}
                    aria-label={`글자 크기 ${SIZE_LABEL[size]}, 누르면 바뀝니다`}
                    className={`${CHIP} ${size !== 'md' ? CHIP_ON : CHIP_OFF}`}
                  >
                    글자 {SIZE_LABEL[size]}
                  </button>
                  <SyncControl syncMs={syncMs} onChange={setSyncMs} hint={<Kbd>, .</Kbd>} />
                </div>
                {ko.enabled && (
                  <button
                    type="button"
                    onClick={() => setKo({ ...ko, mode: nextKoMode(ko.mode) })}
                    aria-pressed={ko.mode !== 'hide'}
                    className={`${CHIP} ${ko.mode !== 'hide' ? CHIP_ON : CHIP_OFF}`}
                  >
                    한국어 {KO_MODE_LABEL[ko.mode]} <Kbd>K</Kbd>
                  </button>
                )}
              </div>
            </>
          )}

        </section>

        {withLines && !blocked && (
          <section
            aria-label="줄 목록"
            className={`mt-3 flex min-h-24 flex-1 flex-col overflow-hidden border-t border-surface/20 lg:mt-0 lg:rounded-2xl lg:border lg:border-surface/20 max-lg:[@media(max-height:700px)]:h-80 max-lg:[@media(max-height:700px)]:flex-none`}
          >
            <div
              ref={listRef}
              className={`relative min-h-0 flex-1 overflow-y-auto px-1 py-1`}
              onWheel={() => (lastUserScroll.current = performance.now())}
              onTouchMove={() => (lastUserScroll.current = performance.now())}
            >
              {data.hasMoreBefore && (
                <button
                  type="button"
                  onClick={() => loadMore('before')}
                  disabled={moreBusy !== null}
                  className="my-1 min-h-11 w-full rounded-lg text-sm font-semibold text-surface/80 underline disabled:opacity-40"
                >
                  {moreBusy === 'before' ? '불러오는 중' : '위로 더 보기'}
                </button>
              )}
              <ul role="list">
                {state.lines.map((l, i) => {
                  const current = i === state.index;
                  const hidden = eng !== 'show' && revealedId !== l.id;
                  return (
                    <li key={l.id}>
                      <button
                        type="button"
                        onClick={() => act.jump(i)}
                        disabled={!ready}
                        aria-current={current ? 'true' : undefined}
                        className={`flex min-h-11 w-full items-start gap-3 rounded-lg border-l-4 px-3 py-2 text-left ${
                          current ? 'border-marker bg-surface/15' : 'border-transparent hover:bg-surface/10'
                        }`}
                      >
                        <span className="w-10 shrink-0 pt-0.5 text-xs tabular-nums text-surface/70">{mmss((data.lines[i] ?? l).start)}</span>
                        <span lang="en" className={`min-w-0 break-words ${hidden ? 'blur-sm select-none' : ''}`}>
                          {l.text}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {data.hasMoreAfter && (
                <button
                  type="button"
                  onClick={() => loadMore('after')}
                  disabled={moreBusy !== null}
                  className="my-1 min-h-11 w-full rounded-lg text-sm font-semibold text-surface/80 underline disabled:opacity-40"
                >
                  {moreBusy === 'after' ? '불러오는 중' : '아래로 더 보기'}
                </button>
              )}
              {moreFailed && (
                <p role="status" className="px-3 pb-2 text-sm text-surface/80">
                  더 불러오지 못했어요. 다시 눌러 보세요.
                </p>
              )}
            </div>
          </section>
        )}
      </div>

      {ccOpen && (
        <CaptionSheet
          eng={eng}
          size={size}
          syncMs={syncMs}
          onEng={setEng}
          onSize={setSize}
          onSync={setSyncMs}
          onClose={() => {
            setCcOpen(false);
            ccButton.current?.focus();
          }}
        />
      )}
    </div>
  );
}

export function ClipStudy({ param }: { param: string | null }) {
  const target = parseClipParam(param);
  if (!target) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-ink p-6 text-center text-surface">
        <p className="font-semibold">열 수 없는 클립 주소예요.</p>
        <button type="button" onClick={closeClip} className="min-h-11 rounded-full bg-surface px-5 font-semibold text-ink">
          닫기
        </button>
      </div>
    );
  }
  return <Study key={`${target.videoId}:${target.t}`} target={target} />;
}
