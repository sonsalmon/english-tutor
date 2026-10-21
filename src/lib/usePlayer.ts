import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ClipSegments } from './api';
import { initialState, POLL_MS, START_LEAD_S, step, type PlayerAction, type PlayerEvent, type PlayerState } from './playerMachine';

type YTPlayer = {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  unMute(): void;
  setVolume(volume: number): void;
  getCurrentTime(): number;
  getIframe(): HTMLIFrameElement;
  destroy(): void;
};
type YTStateEvent = { data: number };
type YTApi = {
  Player: new (
    el: HTMLElement,
    opts: {
      videoId: string;
      host: string;
      playerVars: Record<string, string | number>;
      events: { onReady: () => void; onStateChange: (e: YTStateEvent) => void; onError: () => void };
    },
  ) => YTPlayer;
};

declare global {
  interface Window {
    YT?: YTApi;
    onYouTubeIframeAPIReady?: () => void;
  }
}

const API_URL = 'https://www.youtube.com/iframe_api';
const API_TIMEOUT_MS = 10000;
const SLOW_MS = 8000;
const YT_PLAYING = 1;
const YT_BUFFERING = 3;

let apiPromise: Promise<YTApi> | null = null;

function loadApi(): Promise<YTApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  apiPromise ??= new Promise<YTApi>((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    const script = document.createElement('script');
    const fail = () => {
      apiPromise = null;
      script.remove();
      reject(new Error('YouTube 재생 API를 불러오지 못했어요.'));
    };
    const timer = window.setTimeout(fail, API_TIMEOUT_MS);
    window.onYouTubeIframeAPIReady = () => {
      window.clearTimeout(timer);
      previous?.();
      resolve(window.YT as YTApi);
    };
    script.src = API_URL;
    script.async = true;
    script.onerror = () => {
      window.clearTimeout(timer);
      fail();
    };
    document.head.appendChild(script);
  });
  return apiPromise;
}

function run(player: YTPlayer, action: PlayerAction): void {
  if (action.type === 'seek') player.seekTo(action.time, true);
  else if (action.type === 'play') player.playVideo();
  else player.pauseVideo();
}

export type PlayerStatus = 'loading' | 'ready' | 'blocked' | 'failed';

// YouTube IFrame API 플레이어 하나와 줄 상태 머신을 잇는다. 영상 상태는 80ms마다 읽어 머신에 tick으로 넣는다.
export function usePlayer({
  videoId,
  title,
  startTime,
  endTime = null,
  muted = false,
  segments,
  nativeControls,
  enabled,
  onBlocked,
}: {
  videoId: string;
  title: string;
  startTime: number;
  /** 이 시각에서 자동으로 멈춘다(피드 카드). 없으면 끝까지 재생한다. */
  endTime?: number | null;
  /** 처음 만들 때 음소거로 시작한다. 이미 만든 플레이어는 act.unmute로 켠다. */
  muted?: boolean;
  segments: ClipSegments | null;
  nativeControls: boolean;
  enabled: boolean;
  onBlocked: (videoId: string) => void;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<PlayerStatus>('loading');
  const [slow, setSlow] = useState(false);
  const [state, setState] = useState<PlayerState>(() => initialState(startTime, endTime));
  const stateRef = useRef(state);
  const playerRef = useRef<YTPlayer | null>(null);
  const blockedRef = useRef(onBlocked);
  blockedRef.current = onBlocked;
  const startRef = useRef(startTime);
  const mutedRef = useRef(muted);
  const titleRef = useRef(title);
  titleRef.current = title;

  const dispatch = useCallback((event: PlayerEvent) => {
    const result = step(stateRef.current, event);
    if (result.state !== stateRef.current) {
      stateRef.current = result.state;
      setState(result.state);
    }
    const player = playerRef.current;
    if (player) for (const action of result.actions) run(player, action);
  }, []);

  useEffect(() => {
    const host = mountRef.current;
    if (!host || !enabled) return;
    let cancelled = false;
    let poll: number | undefined;
    const slowTimer = window.setTimeout(() => setSlow(true), SLOW_MS);
    const el = document.createElement('div');
    host.appendChild(el);

    loadApi().then(
      (YT) => {
        if (cancelled) return;
        const player = new YT.Player(el, {
          videoId,
          host: 'https://www.youtube-nocookie.com',
          playerVars: {
            autoplay: 1,
            controls: nativeControls ? 1 : 0,
            disablekb: nativeControls ? 0 : 1,
            fs: nativeControls ? 1 : 0,
            rel: 0,
            playsinline: 1,
            modestbranding: 1,
            enablejsapi: 1,
            mute: mutedRef.current ? 1 : 0,
            origin: location.origin,
            start: Math.floor(Math.max(0, startRef.current - START_LEAD_S)),
          },
          events: {
            onReady: () => {
              if (cancelled) return;
              window.clearTimeout(slowTimer);
              setSlow(false);
              setStatus('ready');
              player.getIframe().title = titleRef.current;
              dispatch({ type: 'ready', now: performance.now() });
              poll = window.setInterval(() => {
                try {
                  dispatch({ type: 'tick', time: player.getCurrentTime(), now: performance.now() });
                } catch {
                  /* 플레이어가 정리되는 중: 다음 tick에서 멈춘다 */
                }
              }, POLL_MS);
            },
            onStateChange: (e) => {
              if (e.data !== YT_BUFFERING) dispatch({ type: 'status', playing: e.data === YT_PLAYING });
            },
            onError: () => {
              if (cancelled) return;
              window.clearTimeout(slowTimer);
              window.clearInterval(poll);
              setSlow(false);
              setStatus('blocked');
              blockedRef.current(videoId);
            },
          },
        });
        playerRef.current = player;
      },
      () => {
        if (cancelled) return;
        window.clearTimeout(slowTimer);
        setSlow(false);
        setStatus('failed');
      },
    );

    return () => {
      cancelled = true;
      window.clearTimeout(slowTimer);
      window.clearInterval(poll);
      playerRef.current?.destroy();
      playerRef.current = null;
      host.replaceChildren();
    };
  }, [videoId, enabled, nativeControls, dispatch]);

  useEffect(() => {
    if (segments) dispatch({ type: 'lines', lines: segments.lines, atId: segments.atId });
  }, [segments, dispatch]);

  const act = useMemo(
    () => ({
      prev: () => dispatch({ type: 'prev', now: performance.now() }),
      next: () => dispatch({ type: 'next', now: performance.now() }),
      replay: () => dispatch({ type: 'replay', now: performance.now() }),
      toggle: () => dispatch({ type: 'toggle' }),
      unmute: () => {
        playerRef.current?.unMute();
        playerRef.current?.setVolume(100);
      },
      hold: (open: boolean) => dispatch({ type: open ? 'hold' : 'release' }),
    }),
    [dispatch],
  );

  return { mountRef, status, slow, state, act };
}
