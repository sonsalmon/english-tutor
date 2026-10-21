import { ChevronLeft, ChevronRight, ExternalLink, GraduationCap, Pause, Play, RotateCcw, SkipForward, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { getClipSegments, type Clip, type ClipSegments } from '../lib/api';
import { openClip } from '../lib/clipRoute';
import { lineSource } from '../lib/clipLines';
import { loadPrefs } from '../lib/playerPrefs';
import { DEFAULT_SETTINGS } from '../lib/playerMachine';
import { usePlayer } from '../lib/usePlayer';
import { SpeedChip } from './SpeedChip';
import { WordText } from './WordText';

export function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function startSec(clip: Clip): number {
  return clip.source === 'db' && typeof clip.start === 'number' ? Math.max(0, Math.floor(clip.start)) : 0;
}

function startTime(clip: Clip): number {
  return clip.source === 'db' ? Math.max(0, clip.start_f ?? clip.start ?? 0) : 0;
}

function watchUrl(clip: Clip): string {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(clip.id)}&t=${startSec(clip)}s`;
}

function embedUrl(clip: Clip): string {
  const start = clip.source === 'db' && typeof clip.start === 'number' ? `&start=${startSec(clip)}` : '';
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(clip.id)}?autoplay=1&rel=0&playsinline=1&enablejsapi=1&origin=${encodeURIComponent(location.origin)}${start}`;
}

type Lines = { status: 'loading' } | { status: 'ok'; data: ClipSegments } | { status: 'missing' };

function useClipLines(clip: Clip): Lines {
  const lineable = clip.source === 'db' && typeof clip.start === 'number';
  const [lines, setLines] = useState<Lines>(lineable ? { status: 'loading' } : { status: 'missing' });
  useEffect(() => {
    if (!lineable) return;
    const controller = new AbortController();
    getClipSegments(clip.id, startTime(clip), controller.signal).then(
      (data) => setLines(data.lines.length ? { status: 'ok', data } : { status: 'missing' }),
      () => {
        if (!controller.signal.aborted) setLines({ status: 'missing' });
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.id, lineable]);
  return lines;
}

const BUTTON = 'flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-full border px-2 text-sm font-semibold whitespace-nowrap disabled:opacity-40';
const BUTTON_PLAIN = 'border-line bg-surface hover:bg-paper';
const BUTTON_PRIMARY = 'border-ink bg-ink text-surface';

function ControlButton({ onClick, disabled, label, primary, children }: { onClick: () => void; disabled: boolean; label?: string; primary?: boolean; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={`${BUTTON} ${primary ? BUTTON_PRIMARY : BUTTON_PLAIN}`}
    >
      {children}
    </button>
  );
}

// 요약 화면의 예시 클립 재생기. 줄 정보가 있으면 현재 줄 카드와 이전/다시/다음 줄을 보이고, 없으면 YouTube 기본 컨트롤로 연다.
// example: 같은 표현의 예시 클립 목록 안에서 열었을 때의 위치 표시(label)와 '다음 예시'(onNext가 null이면 마지막이라 눌러지지 않는다).
export function ClipPlayer({
  clip,
  onClose,
  onBlocked,
  example,
}: {
  clip: Clip;
  onClose: () => void;
  onBlocked: (id: string) => void;
  example?: { label: string; onNext: (() => void) | null };
}) {
  const lines = useClipLines(clip);
  const withLines = lines.status === 'ok';
  const [settings] = useState(() => ({ ...DEFAULT_SETTINGS, rate: loadPrefs().rate }));
  const { mountRef, status, slow, state, rates, act, needsTap } = usePlayer({
    videoId: clip.id,
    title: clip.title,
    startTime: startTime(clip),
    segments: lines.status === 'ok' ? lines.data : null,
    nativeControls: !withLines,
    enabled: lines.status !== 'loading',
    onBlocked,
    settings,
  });
  const tapFirst = withLines && needsTap;
  const line = withLines && state.index >= 0 ? state.lines[state.index] : null;
  const ready = status === 'ready';
  const blocked = status === 'blocked';
  const root = useRef<HTMLDivElement>(null);
  const shown = line !== null;

  // 줄 정보가 도착하면 카드가 커지므로, 줄 이동 버튼이 화면 아래로 밀리지 않게 카드 전체가 보이는 위치로 스크롤한다.
  useEffect(() => {
    if (!shown) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    root.current?.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
  }, [shown]);

  return (
    <div ref={root} className="p-3">
      {blocked ? (
        <div role="alert" className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-lg border border-line bg-paper p-4 text-center">
          <p className="font-semibold">이 영상은 앱 안에서 틀 수 없어요.</p>
          <a
            href={watchUrl(clip)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-ink px-4 text-sm font-semibold text-surface"
          >
            <ExternalLink size={18} aria-hidden />
            YouTube에서 보기 ({mmss(startSec(clip))}부터)
          </a>
        </div>
      ) : status === 'failed' ? (
        <div className="aspect-video w-full overflow-hidden rounded-lg bg-ink">
          <iframe
            src={embedUrl(clip)}
            title={clip.title}
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
            className="size-full border-0"
          />
        </div>
      ) : (
        <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-ink">
          <div ref={mountRef} className={`absolute inset-0 [&_iframe]:size-full [&_iframe]:border-0 ${withLines && !tapFirst ? '[&_iframe]:pointer-events-none' : ''}`} />
          {!ready && (
            <div role="status" aria-label="영상을 불러오는 중" className="absolute inset-0 flex items-center justify-center bg-ink">
              <img src={clip.thumbnail} alt="" className="absolute inset-0 size-full object-cover opacity-60" />
              <span className="relative size-8 animate-spin rounded-full border-2 border-surface/40 border-t-surface" />
            </div>
          )}
          {tapFirst && (
            <p role="status" className="pointer-events-none absolute inset-x-0 bottom-0 bg-ink/85 px-3 py-2 text-center text-sm font-semibold text-surface">
              영상을 한 번 눌러 시작하세요.
            </p>
          )}
          {withLines && ready && !tapFirst && (
            <>
              <button
                type="button"
                onClick={act.toggle}
                aria-label={state.playing ? '일시정지' : '재생'}
                className="absolute inset-0 cursor-pointer"
              />
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

      {withLines && !blocked && status !== 'failed' && line && (
        <>
          <div className="mt-3 rounded-xl border border-line bg-paper p-3">
            <p key={line.id} lang="en" className="line-in text-xl leading-snug font-semibold break-words">
              <WordText
                text={line.text}
                onOpenChange={act.hold}
                source={lineSource(clip.id, clip.title, line)}
                units={clip.phrase ? [{ text: clip.phrase }] : undefined}
                learn
              />
            </p>
            <p className="mt-1 text-sm text-ink-soft">{mmss(line.start)}부터</p>
          </div>
          <div role="group" aria-label="줄 이동" className="mt-2 grid grid-cols-[1fr_1fr_3rem_1fr_3.25rem] gap-2">
            <ControlButton onClick={act.prev} disabled={!ready || state.index <= 0}>
              <ChevronLeft size={18} aria-hidden />
              이전 줄
            </ControlButton>
            <ControlButton onClick={act.replay} disabled={!ready}>
              <RotateCcw size={16} aria-hidden />
              다시
            </ControlButton>
            <ControlButton onClick={act.toggle} disabled={!ready} label={state.playing ? '일시정지' : '재생'} primary>
              {state.playing ? <Pause size={20} fill="currentColor" aria-hidden /> : <Play size={20} fill="currentColor" aria-hidden />}
            </ControlButton>
            <ControlButton onClick={act.next} disabled={!ready || state.index >= state.lines.length - 1}>
              다음 줄
              <ChevronRight size={18} aria-hidden />
            </ControlButton>
            <SpeedChip rate={state.rate} rates={rates} disabled={!ready} onChange={act.setRate} className={`${BUTTON} ${BUTTON_PLAIN} px-0`} />
          </div>
        </>
      )}
      {lines.status === 'missing' && clip.source === 'db' && !blocked && (
        <p role="status" className="mt-2 text-sm text-ink-soft">
          줄 정보를 못 불러왔어요.
        </p>
      )}

      {slow && !blocked && (
        <p className="mt-2 text-sm text-ink-soft">
          <a
            href={watchUrl(clip)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 underline"
          >
            <ExternalLink size={16} aria-hidden />
            안 나오면 YouTube에서 보기 ({mmss(startSec(clip))}부터)
          </a>
        </p>
      )}
      <div className="mt-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold break-words">{clip.title}</p>
          <p className="text-sm text-ink-soft">{clip.channel}</p>
          {!line && clip.source === 'db' && clip.text && (
            <p className="mt-1 text-sm break-words">
              <span lang="en">“{clip.text}”</span> <span className="text-ink-soft">{mmss(clip.start ?? 0)}부터</span>
            </p>
          )}
        </div>
        <div className="flex shrink-0 flex-col gap-2">
          {withLines && !blocked && status !== 'failed' && (
            <button
              type="button"
              onClick={() => openClip(clip.id, line?.start ?? startTime(clip))}
              className="flex min-h-11 items-center gap-1.5 rounded-full border border-ink bg-ink px-3 text-sm font-semibold text-surface"
            >
              <GraduationCap size={18} aria-hidden />
              공부하기
            </button>
          )}
          {example && (
            <button
              type="button"
              onClick={example.onNext ?? undefined}
              disabled={!example.onNext}
              className="flex min-h-11 items-center justify-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold whitespace-nowrap hover:bg-paper disabled:opacity-40"
            >
              <SkipForward size={18} aria-hidden />
              {example.onNext ? '다음 예시' : '마지막 예시'}
              {example.label && <span className="font-normal text-ink-soft">{example.label}</span>}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold hover:bg-paper"
          >
            <X size={18} aria-hidden />
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
