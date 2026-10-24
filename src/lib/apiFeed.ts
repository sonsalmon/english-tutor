export type FeedFilter = 'mine' | 'browse' | 'native';
export type NativeInfo = {
  expression: string;
  kind: string;
  meaning_ko: string;
  say_ko: string;
  why_hard: string;
  register: string;
  example: string;
  per_million: number;
};
export type FeedClip = {
  id: string;
  video_id: string;
  start: number;
  end: number;
  text: string;
  title: string;
  channel: string;
  source: 'mine' | 'browse' | 'native';
  term: string | null;
  match: string | null;
  native: NativeInfo | null;
};
export type FeedPage = { available: boolean; clips: FeedClip[]; terms: number; native: number };

const SAY_MAX_CHARS = 40;

// 카드 위에 크게 보여 줄 “말하고 싶은 한국어 한 줄”. say_ko, 없으면 meaning_ko의 첫 항목, 그마저 없으면 사전 뜻(gloss).
export function sayLine(native: NativeInfo | null, gloss = ''): string {
  if (native?.say_ko) return native.say_ko;
  const first = native?.meaning_ko.split(/[;,，、/]/)[0]?.trim();
  return first || gloss.trim();
}

// 서버가 준 native 덩어리를 검증한다. 표현과 뜻이 없으면 일반 클립처럼 다룬다.
export function parseNative(raw: any): NativeInfo | null {
  const expression = String(raw?.expression ?? '').trim();
  const meaning = String(raw?.meaning_ko ?? '').trim();
  if (!expression || !meaning) return null;
  return {
    expression,
    kind: String(raw?.kind ?? ''),
    meaning_ko: meaning,
    say_ko: String(raw?.say_ko ?? '').trim().slice(0, SAY_MAX_CHARS),
    why_hard: String(raw?.why_hard ?? ''),
    register: String(raw?.register ?? ''),
    example: String(raw?.example ?? ''),
    per_million: Number(raw?.per_million) || 0,
  };
}

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

// 플레이어가 재생 오류를 낸 영상을 서버에 알려 다음부터 피드·예시 클립에서 빼게 한다. 실패해도 화면은 계속 쓴다.
export async function reportBlockedVideo(videoId: string): Promise<boolean> {
  try {
    const res = await fetch('/api/clips/blocked', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId }),
      keepalive: true,
    });
    return res.ok;
  } catch {
    return false;
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
    source: c?.source === 'mine' ? 'mine' : c?.source === 'native' && parseNative(c?.native) ? 'native' : 'browse',
    term: typeof c?.term === 'string' && c.term ? c.term : null,
    match: typeof c?.match === 'string' && c.match ? c.match : null,
    native: parseNative(c?.native),
  }));
  return {
    available: data?.available !== false,
    clips: clips.filter((c: FeedClip) => c.id && c.video_id),
    terms: Number(data?.terms) || 0,
    native: Number(data?.native) || 0,
  };
}
