import { Bookmark, Play, Square } from 'lucide-react';
import { useState } from 'react';
import { clipThumbnail, mutedEmbedUrl, type SharedClip } from '../lib/share';

// 통화 중 파트너가 보낸 장면. 마이크에 소리가 섞이지 않게 저절로 재생하지 않고, 눌러도 소리 없이만 연다.
export function SharedClipCard({ clip, from, onLater }: { clip: SharedClip; from: string; onLater: () => void }) {
  const [playing, setPlaying] = useState(false);
  return (
    <section role="group" aria-label={`${from}님이 보낸 장면`} className="rounded-2xl border border-line bg-surface p-3">
      <p className="text-xs font-semibold text-ink-soft">{from}님이 보낸 장면</p>
      <div className="mt-2 flex gap-3">
        {playing ? (
          <iframe
            src={mutedEmbedUrl(clip)}
            title={clip.title || '보낸 영상'}
            allow="autoplay; encrypted-media; picture-in-picture"
            className="aspect-video w-32 shrink-0 self-start rounded-lg border-0 bg-line"
          />
        ) : (
          <img src={clipThumbnail(clip.video_id)} alt="" width={320} height={180} className="aspect-video w-32 shrink-0 self-start rounded-lg bg-line object-cover" />
        )}
        <div className="min-w-0 flex-1">
          <p lang="en" className="line-clamp-3 text-[15px] leading-snug break-words">
            “{clip.text}”
          </p>
          {clip.title && <p className="mt-1 truncate text-sm text-ink-soft">{clip.title}</p>}
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={() => setPlaying((value) => !value)}
          className="flex h-11 flex-1 items-center justify-center gap-1.5 rounded-full border border-line text-[15px] font-semibold active:bg-paper"
        >
          {playing ? <Square size={16} aria-hidden /> : <Play size={16} aria-hidden />}
          {playing ? '닫기' : '소리 없이 보기'}
        </button>
        <button
          type="button"
          onClick={onLater}
          className="flex h-11 flex-1 items-center justify-center gap-1.5 rounded-full bg-ink text-[15px] font-semibold text-white active:opacity-80"
        >
          <Bookmark size={16} aria-hidden />
          통화 끝나고 보기
        </button>
      </div>
    </section>
  );
}
