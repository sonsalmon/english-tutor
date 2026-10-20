import { ExternalLink, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { getCallClips, type Clip, type ClipResult } from '../lib/api';

const MAX_CLIPS = 5;

function mmss(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function startSec(clip: Clip): number {
  return clip.source === 'db' && typeof clip.start === 'number' ? Math.max(0, Math.floor(clip.start)) : 0;
}

function embedUrl(clip: Clip): string {
  const start = startSec(clip) > 0 || (clip.source === 'db' && typeof clip.start === 'number') ? `&start=${startSec(clip)}` : '';
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(clip.id)}?autoplay=1&rel=0&playsinline=1&enablejsapi=1&origin=${encodeURIComponent(location.origin)}${start}`;
}

function watchUrl(clip: Clip): string {
  return `https://www.youtube.com/watch?v=${encodeURIComponent(clip.id)}&t=${startSec(clip)}s`;
}

const BLOCKED_KEY = 'english-tutor.blocked-clips';
const MAX_BLOCKED = 200;
const READY_TIMEOUT_MS = 8000;

function loadBlocked(): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(BLOCKED_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function rememberBlocked(id: string): void {
  try {
    const next = [...loadBlocked().filter((v) => v !== id), id].slice(-MAX_BLOCKED);
    localStorage.setItem(BLOCKED_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: skip remembering */
  }
}

const YT_ORIGINS = new Set(['https://www.youtube-nocookie.com', 'https://www.youtube.com']);

function Matched({ clip }: { clip: Clip }) {
  if (clip.source !== 'db' || !clip.text) return null;
  return (
    <span className="mt-1 block text-sm break-words">
      <span lang="en" className="line-clamp-2">“{clip.text}”</span>
      <span className="text-ink-soft">{mmss(clip.start ?? 0)}부터</span>
    </span>
  );
}

type State = { stem: string; result: ClipResult | null; failed: boolean };

function Quiet({ children }: { children: string }) {
  return <p className="leading-relaxed text-ink-soft">{children}</p>;
}

function Skeleton() {
  return (
    <div role="status" aria-label="관련 영상을 찾는 중" className="divide-y divide-line rounded-2xl border border-line bg-surface">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex animate-pulse gap-3 p-3">
          <div className="aspect-video w-32 shrink-0 self-start rounded-lg bg-line" />
          <div className="flex-1 space-y-2 py-1">
            <div className="h-4 rounded bg-line" />
            <div className="h-4 w-2/3 rounded bg-line" />
            <div className="h-3 w-1/3 rounded bg-line" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Player({ clip, onClose, onBlocked }: { clip: Clip; onClose: () => void; onBlocked: (id: string) => void }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    setBlocked(false);
    let alive = true;
    let heard = false;
    const giveUp = () => {
      if (!alive) return;
      alive = false;
      setBlocked(true);
      onBlocked(clip.id);
    };
    const timer = window.setTimeout(giveUp, READY_TIMEOUT_MS);
    const listen = () => frame.current?.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: 1, channel: 'widget' }), 'https://www.youtube-nocookie.com');
    const poll = window.setInterval(() => {
      if (heard) window.clearInterval(poll);
      else listen();
    }, 1000);
    const onMessage = (e: MessageEvent) => {
      if (!YT_ORIGINS.has(e.origin) || e.source !== frame.current?.contentWindow || typeof e.data !== 'string') return;
      let data: { event?: unknown };
      try {
        data = JSON.parse(e.data) as { event?: unknown };
      } catch {
        return;
      }
      if (data.event === 'onError') {
        window.clearTimeout(timer);
        giveUp();
      } else if (data.event === 'onReady' || data.event === 'infoDelivery' || data.event === 'initialDelivery') {
        heard = true;
        window.clearTimeout(timer);
      }
    };
    window.addEventListener('message', onMessage);
    const el = frame.current;
    el?.addEventListener('load', listen);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      window.clearInterval(poll);
      window.removeEventListener('message', onMessage);
      el?.removeEventListener('load', listen);
    };
  }, [clip.id, onBlocked]);

  return (
    <div className="p-3">
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
      ) : (
        <div className="aspect-video w-full overflow-hidden rounded-lg bg-ink">
          <iframe
            ref={frame}
            src={embedUrl(clip)}
            title={clip.title}
            allow="encrypted-media; picture-in-picture"
            allowFullScreen
            className="size-full border-0"
          />
        </div>
      )}
      <div className="mt-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold break-words">{clip.title}</p>
          <p className="text-sm text-ink-soft">{clip.channel}</p>
          {clip.source === 'db' && clip.text && (
            <p className="mt-1 text-sm break-words">
              <span lang="en">“{clip.text}”</span> <span className="text-ink-soft">{mmss(clip.start ?? 0)}부터</span>
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold hover:bg-paper"
        >
          <X size={18} aria-hidden />
          닫기
        </button>
      </div>
    </div>
  );
}

function ClipCard({ clip, onPlay }: { clip: Clip; onPlay: () => void }) {
  return (
    <button type="button" onClick={onPlay} aria-label={`영상 재생, ${clip.title}`} className="flex w-full gap-3 p-3 text-left hover:bg-paper">
      <img
        src={clip.thumbnail}
        alt=""
        loading="lazy"
        width={320}
        height={180}
        className="aspect-video w-32 shrink-0 self-start rounded-lg bg-line object-cover"
      />
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 block font-semibold break-words">{clip.title}</span>
        <span className="mt-1 block truncate text-sm text-ink-soft">{clip.channel}</span>
        <Matched clip={clip} />
      </span>
    </button>
  );
}

export function ClipList({ stem }: { stem: string }) {
  const [state, setState] = useState<State>({ stem: '', result: null, failed: false });
  const [playing, setPlaying] = useState<string | null>(null);
  const [blockedAtLoad, setBlockedAtLoad] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    setPlaying(null);
    getCallClips(stem, controller.signal).then(
      (result) => {
        setBlockedAtLoad(loadBlocked());
        setState({ stem, result, failed: false });
      },
      () => {
        if (!controller.signal.aborted) setState({ stem, result: null, failed: true });
      },
    );
    return () => controller.abort();
  }, [stem]);

  const current = state.stem === stem ? state : null;
  const result = current?.result ?? null;
  const clips = [...(result?.clips ?? [])]
    .sort((a, b) => Number(blockedAtLoad.includes(a.id)) - Number(blockedAtLoad.includes(b.id)))
    .slice(0, MAX_CLIPS);

  return (
    <section className="mt-8">
      <h3 className="text-lg font-bold">관련 영상</h3>
      {result?.status === 'ok' && result.query && (
        <p className="mt-1 mb-3 text-sm break-words text-ink-soft">
          {clips.length > 0 && clips.every((c) => c.source === 'db') ? (
            <>
              자막에서 ‘<span lang="en">{[...new Set(clips.map((c) => c.phrase).filter(Boolean))].join(', ')}</span>’가 나오는 장면이에요.
            </>
          ) : (
            <>
              ‘<span lang="en">{result.query}</span>’로 찾았어요.
            </>
          )}
        </p>
      )}
      <div className={result?.status === 'ok' ? '' : 'mt-2'}>
        {!current ? (
          <Skeleton />
        ) : current.failed || !result ? (
          <Quiet>영상을 불러오지 못했어요. 잠시 뒤에 다시 열어 보세요.</Quiet>
        ) : result.status === 'no_key' ? (
          <Quiet>유튜브 키가 없어 영상을 찾지 못했어요.</Quiet>
        ) : result.status === 'no_query' ? (
          <Quiet>이 통화는 검색어가 없어 영상을 찾지 않았어요.</Quiet>
        ) : result.status === 'error' ? (
          <Quiet>유튜브에서 영상을 가져오지 못했어요. 잠시 뒤에 다시 열어 보세요.</Quiet>
        ) : clips.length === 0 ? (
          <Quiet>찾은 영상이 없어요.</Quiet>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
            {clips.map((clip) => (
              <li key={clip.id}>
                {playing === clip.id ? (
                  <Player clip={clip} onClose={() => setPlaying(null)} onBlocked={rememberBlocked} />
                ) : (
                  <ClipCard clip={clip} onPlay={() => setPlaying(clip.id)} />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
