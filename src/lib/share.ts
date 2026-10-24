// 통화 중 보내기/받기: 서버(call_tools.py)가 보내는 메시지 해석과 화면용 보조 함수.

export const SHARE_MAX = 1000;

export type SharedClip = { video_id: string; start: number; end: number; text: string; title: string; channel: string };
export type ShareAck = { id: string; ok: boolean; url?: string; title?: string; opened?: boolean };

const VIDEO_ID = /^[A-Za-z0-9_-]{6,20}$/;
// 서버 call_tools._URL_RE와 같은 규칙: http(s)://, www., youtube.com/, youtu.be/ 로 시작하는 덩어리.
const URL_RE = /(?:https?:\/\/|www\.|(?:m\.|music\.)?youtube\.com\/|youtu\.be\/)[^\s<>"'「」]+/i;
const TRAILING = /[.,;:!?)\]}>'"]+$/;

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

// {type:'shared_clip', clip:{...}} 메시지의 clip. 영상 id가 틀리거나 줄이 비면 null.
export function parseSharedClip(data: unknown): SharedClip | null {
  const raw = (data as { clip?: unknown } | null | undefined)?.clip as Record<string, unknown> | null | undefined;
  if (!raw || typeof raw !== 'object') return null;
  const start = finiteNumber(raw.start);
  const end = finiteNumber(raw.end);
  if (typeof raw.video_id !== 'string' || !VIDEO_ID.test(raw.video_id) || start === null || end === null) return null;
  if (typeof raw.text !== 'string' || !raw.text.trim()) return null;
  return {
    video_id: raw.video_id,
    start,
    end: Math.max(start, end),
    text: raw.text.trim(),
    title: typeof raw.title === 'string' ? raw.title : '',
    channel: typeof raw.channel === 'string' ? raw.channel : '',
  };
}

// {type:'share_ack', id, ok, url?, title?, opened?} 메시지. 보낸 글과 짝을 맞출 id가 없으면 null.
export function parseShareAck(data: unknown): ShareAck | null {
  const raw = data as Record<string, unknown> | null | undefined;
  if (!raw || raw.type !== 'share_ack' || typeof raw.id !== 'string') return null;
  return {
    id: raw.id,
    ok: raw.ok === true,
    ...(typeof raw.url === 'string' ? { url: raw.url } : {}),
    ...(typeof raw.title === 'string' ? { title: raw.title } : {}),
    ...(typeof raw.opened === 'boolean' ? { opened: raw.opened } : {}),
  };
}

// 글 안의 첫 주소(http가 없으면 https를 붙인다). 없으면 null.
export function firstUrl(text: string): string | null {
  const match = URL_RE.exec(text);
  if (!match) return null;
  const url = match[0].replace(TRAILING, '');
  if (!url) return null;
  return /^https?:\/\//i.test(url) ? url : `https://${url}`;
}

// 보낸 글에서 주소 부분을 뺀 나머지(말풍선 본문).
export function withoutUrl(text: string): string {
  return text.replace(new RegExp(URL_RE.source, 'gi'), ' ').replace(/\s+/g, ' ').trim();
}

export function linkLabel(url: string, title?: string): string {
  if (title?.trim()) return title.trim();
  try {
    const parsed = new URL(url);
    const path = parsed.pathname === '/' ? '' : parsed.pathname;
    return `${parsed.hostname.replace(/^www\./, '')}${path}`;
  } catch {
    return url;
  }
}

export function clipKey(clip: Pick<SharedClip, 'video_id' | 'start'>): string {
  return `${clip.video_id}:${clip.start}`;
}

export function clipThumbnail(videoId: string): string {
  return `https://i.ytimg.com/vi/${encodeURIComponent(videoId)}/mqdefault.jpg`;
}

// 소리 없이 미리 보는 삽입 주소. 통화 중에는 마이크에 소리가 섞이지 않게 mute=1로만 연다.
export function mutedEmbedUrl(clip: SharedClip): string {
  const params = new URLSearchParams({
    autoplay: '1',
    mute: '1',
    playsinline: '1',
    rel: '0',
    start: String(Math.floor(clip.start)),
    end: String(Math.ceil(clip.end) + 1),
  });
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(clip.video_id)}?${params}`;
}
