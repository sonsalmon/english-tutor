import { ExternalLink, Pause, Play, RotateCcw, Volume2 } from 'lucide-react';
import { useState } from 'react';
import type { FeedClip } from '../lib/apiFeed';
import { usePlayer } from '../lib/usePlayer';

const BUTTON =
  'flex min-h-11 items-center gap-1.5 rounded-full px-4 text-sm font-semibold whitespace-nowrap focus-visible:outline-white disabled:opacity-40';

function watchUrl(clip: FeedClip): string {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(clip.video_id)}&t=${Math.floor(clip.start)}s`;
}

// 재생 API를 못 불러왔을 때만 쓰는 기본 임베드.
function embedUrl(clip: FeedClip): string {
  const params = new URLSearchParams({
    autoplay: '1',
    mute: '1',
    controls: '0',
    rel: '0',
    playsinline: '1',
    modestbranding: '1',
    start: String(Math.floor(clip.start)),
    end: String(Math.ceil(clip.end) + 1),
    origin: location.origin,
  });
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(clip.video_id)}?${params}`;
}

function Thumbnail({ clip }: { clip: FeedClip }) {
  return <img src={`https://i.ytimg.com/vi/${encodeURIComponent(clip.video_id)}/hqdefault.jpg`} alt="" loading="lazy" className="size-full object-cover opacity-80" />;
}

// 플레이어가 켜진 동안만 마운트한다. 카드가 비활성이 되면 통째로 사라져 영상 플레이어도 정리된다.
function Live({ clip, muted, onBlocked }: { clip: FeedClip; muted: boolean; onBlocked: () => void }) {
  const [soundOn, setSoundOn] = useState(!muted);
  const { mountRef, status, state, act } = usePlayer({
    videoId: clip.video_id,
    title: clip.title,
    startTime: clip.start,
    endTime: clip.end,
    muted,
    segments: null,
    nativeControls: false,
    enabled: true,
    onBlocked,
  });
  const ready = status === 'ready';

  if (status === 'failed') {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-xl bg-black">
        <iframe src={embedUrl(clip)} title={clip.title} allow="autoplay; encrypted-media; picture-in-picture" className="size-full border-0" />
      </div>
    );
  }

  const label = state.ended ? '처음부터 다시 보기' : state.playing ? '일시정지' : '재생';
  return (
    <div>
      <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
        <div ref={mountRef} className="absolute inset-0 [&_iframe]:pointer-events-none [&_iframe]:size-full [&_iframe]:border-0" />
        {!ready && (
          <div role="status" aria-label="영상을 불러오는 중" className="absolute inset-0 flex items-center justify-center bg-black">
            <span className="absolute inset-0">
              <Thumbnail clip={clip} />
            </span>
            <span className="relative size-8 animate-spin rounded-full border-2 border-white/40 border-t-white" />
          </div>
        )}
        {ready && (
          <>
            <button
              type="button"
              onClick={state.ended ? act.replay : act.toggle}
              aria-label={label}
              className="absolute inset-0 cursor-pointer focus-visible:outline-white"
            />
            {!state.playing && (
              <span aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <span className="flex size-[4.5rem] items-center justify-center rounded-full bg-black/60 text-white">
                  {state.ended ? <RotateCcw size={28} /> : <Play size={28} fill="currentColor" />}
                </span>
              </span>
            )}
          </>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="button" onClick={act.replay} disabled={!ready} className={`${BUTTON} bg-white/15 text-white`}>
          <RotateCcw size={18} aria-hidden />
          다시 보기
        </button>
        <button type="button" onClick={act.toggle} disabled={!ready || state.ended} aria-label={state.playing ? '일시정지' : '재생'} className={`${BUTTON} bg-white/15 text-white`}>
          {state.playing ? <Pause size={18} fill="currentColor" aria-hidden /> : <Play size={18} fill="currentColor" aria-hidden />}
          {state.playing ? '멈춤' : '재생'}
        </button>
        {!soundOn && (
          <button
            type="button"
            onClick={() => {
              setSoundOn(true);
              act.unmute();
            }}
            className={`${BUTTON} bg-white text-ink`}
          >
            <Volume2 size={18} aria-hidden />
            소리 켜기
          </button>
        )}
      </div>
    </div>
  );
}

// 피드 카드의 영상. 켜진 카드만 재생하고, 움직임 줄이기를 켠 사람에게는 누를 때까지 재생하지 않는다.
// 자동 재생은 음소거로 시작하고, 사람이 눌러서 시작하면 소리와 함께 시작한다.
export function FeedPlayer({ clip, active, autoplay, onBlocked }: { clip: FeedClip; active: boolean; autoplay: boolean; onBlocked: () => void }) {
  const [started, setStarted] = useState(false);
  const [prevActive, setPrevActive] = useState(active);
  const [blocked, setBlocked] = useState(false);
  if (active !== prevActive) {
    setPrevActive(active);
    if (!active) setStarted(false);
  }
  const playing = active && (autoplay || started);

  if (blocked) {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-xl bg-black">
        <div role="alert" className="flex size-full flex-col items-center justify-center gap-3 p-4 text-center text-white">
          <p className="font-semibold">이 영상은 앱 안에서 틀 수 없어요.</p>
          <a href={watchUrl(clip)} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-white px-4 text-sm font-semibold text-ink focus-visible:outline-white">
            <ExternalLink size={18} aria-hidden />
            YouTube에서 보기
          </a>
        </div>
      </div>
    );
  }
  if (playing) {
    return (
      <Live
        clip={clip}
        muted={!started}
        onBlocked={() => {
          setBlocked(true);
          onBlocked();
        }}
      />
    );
  }
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
      <button type="button" onClick={() => setStarted(true)} disabled={!active} aria-label={`영상 재생, ${clip.title}`} className="relative block size-full focus-visible:outline-white">
        <Thumbnail clip={clip} />
        <span className="absolute inset-0 grid place-items-center">
          <span className="grid size-14 place-items-center rounded-full bg-black/60 text-white">
            <Play size={28} aria-hidden />
          </span>
        </span>
      </button>
    </div>
  );
}
