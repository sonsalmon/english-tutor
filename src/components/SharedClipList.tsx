import { openClip } from '../lib/clipRoute';
import { clipThumbnail, type SharedClip } from '../lib/share';

export function SharedClipList({ clips, from }: { clips: SharedClip[]; from: string }) {
  if (!clips.length) return null;
  return (
    <section className="mt-8">
      <h2 className="text-lg font-bold">{from}님이 통화 중에 보낸 장면</h2>
      <ul className="mt-3 divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
        {clips.map((clip) => (
          <li key={`${clip.video_id}:${clip.start}`}>
            <button
              type="button"
              onClick={() => openClip(clip.video_id, clip.start)}
              aria-label={`장면 보기, ${clip.title || clip.text}`}
              className="flex w-full gap-3 p-3 text-left hover:bg-paper"
            >
              <img src={clipThumbnail(clip.video_id)} alt="" loading="lazy" width={320} height={180} className="aspect-video w-32 shrink-0 self-start rounded-lg bg-line object-cover" />
              <span className="min-w-0 flex-1">
                <span lang="en" className="line-clamp-3 block break-words">
                  “{clip.text}”
                </span>
                {clip.title && <span className="mt-1 block truncate text-sm text-ink-soft">{clip.title}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
