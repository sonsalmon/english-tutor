import { useEffect, useState } from 'react';
import { getCallClips, type Clip, type ClipResult } from '../lib/api';
import { reportBlockedVideo } from '../lib/apiFeed';
import { getPhraseClips } from '../lib/review';
import { ClipPlayer, mmss } from './ClipPlayer';

const MAX_CLIPS = 5;

const BLOCKED_KEY = 'english-tutor.blocked-clips';
const MAX_BLOCKED = 200;

function loadBlocked(): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(BLOCKED_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === 'string') : [];
  } catch {
    return [];
  }
}

function rememberBlocked(id: string): void {
  void reportBlockedVideo(id);
  try {
    const next = [...loadBlocked().filter((v) => v !== id), id].slice(-MAX_BLOCKED);
    localStorage.setItem(BLOCKED_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: skip remembering */
  }
}

function Matched({ clip }: { clip: Clip }) {
  if (clip.source !== 'db' || !clip.text) return null;
  return (
    <span className="mt-1 block text-sm break-words">
      <span lang="en" className="line-clamp-4">“{clip.text}”</span>
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

function ClipRows({ clips }: { clips: Clip[] }) {
  const [playing, setPlaying] = useState<string | null>(null);
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
      {clips.map((clip) => (
        <li key={clip.id}>
          {playing === clip.id ? (
            <ClipPlayer clip={clip} onClose={() => setPlaying(null)} onBlocked={rememberBlocked} />
          ) : (
            <ClipCard clip={clip} onPlay={() => setPlaying(clip.id)} />
          )}
        </li>
      ))}
    </ul>
  );
}

// 표현 하나를 말하는 장면. 자막 DB가 없거나 찾은 게 없거나 불러오지 못하면 영역을 통째로 숨긴다.
export function PhraseClips({ phrase }: { phrase: string }) {
  const [state, setState] = useState<{ phrase: string; clips: Clip[] | null }>({ phrase: '', clips: null });

  useEffect(() => {
    const controller = new AbortController();
    getPhraseClips(phrase, 3, controller.signal).then(
      (result) => setState({ phrase, clips: result.status === 'ok' ? result.clips : [] }),
      () => {
        if (!controller.signal.aborted) setState({ phrase, clips: [] });
      },
    );
    return () => controller.abort();
  }, [phrase]);

  const clips = state.phrase === phrase ? state.clips : null;
  if (clips && clips.length === 0) return null;
  return (
    <div className="mt-4">
      <h5 className="text-sm font-semibold text-ink-soft">예시 클립</h5>
      <div className="mt-2">{clips ? <ClipRows clips={clips} /> : <Skeleton />}</div>
    </div>
  );
}

export function ClipList({ stem }: { stem: string }) {
  const [state, setState] = useState<State>({ stem: '', result: null, failed: false });
  const [blockedAtLoad, setBlockedAtLoad] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
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
          <ClipRows clips={clips} />
        )}
      </div>
    </section>
  );
}
