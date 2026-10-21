export type FeedFilter = 'mine' | 'browse';
export type FeedClip = {
  id: string;
  video_id: string;
  start: number;
  end: number;
  text: string;
  title: string;
  channel: string;
  source: 'mine' | 'browse';
  term: string | null;
};
export type FeedPage = { available: boolean; clips: FeedClip[]; terms: number };

export const SEEN_KEY = 'english-tutor.feed-seen';
export const SEEN_CAP = 200;
export const PAGE_SIZE = 6;

// 본 클립 id 목록에 새 id를 붙이고 최근 cap개만 남긴다(중복은 뒤로 옮긴다).
export function rememberSeen(list: string[], ids: string[], cap: number = SEEN_CAP): string[] {
  const merged = [...list.filter((id) => !ids.includes(id)), ...ids];
  return merged.slice(-cap);
}

export function loadSeen(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SEEN_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string').slice(-SEEN_CAP) : [];
  } catch {
    return [];
  }
}

export function saveSeen(list: string[]): void {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(list.slice(-SEEN_CAP)));
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 방문에서만 중복을 피한다.
  }
}

export async function getFeed(filter: FeedFilter, seen: string[], signal?: AbortSignal): Promise<FeedPage> {
  const params = new URLSearchParams({ filter, limit: String(PAGE_SIZE), seen: seen.slice(-SEEN_CAP).join(',') });
  let res: Response;
  try {
    res = await fetch(`/api/feed?${params}`, { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (!res.ok) throw new Error('클립을 불러오지 못했어요.');
  const data = await res.json();
  const clips = (Array.isArray(data?.clips) ? data.clips : []).map((c: any): FeedClip => ({
    id: String(c?.id ?? ''),
    video_id: String(c?.video_id ?? ''),
    start: Number(c?.start) || 0,
    end: Number(c?.end) || 0,
    text: String(c?.text ?? ''),
    title: String(c?.title ?? ''),
    channel: String(c?.channel ?? ''),
    source: c?.source === 'mine' ? 'mine' : 'browse',
    term: typeof c?.term === 'string' && c.term ? c.term : null,
  }));
  return { available: data?.available !== false, clips: clips.filter((c: FeedClip) => c.id && c.video_id), terms: Number(data?.terms) || 0 };
}
