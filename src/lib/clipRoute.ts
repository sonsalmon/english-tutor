import { go } from './router';

const VIDEO_ID = /^[A-Za-z0-9_-]{6,20}$/;

export type ClipTarget = { videoId: string; t: number };

// 시각은 소수 둘째 자리까지 둔다. 정수로 내리면 줄 시작(376.8)이 앞 줄(376)로 열린다.
export function clipHash(videoId: string, t: number): string {
  return `#/clip/${encodeURIComponent(videoId)}?t=${Math.max(0, Math.round(t * 100) / 100)}`;
}

// #/clip/<영상 id>?t=<초>의 "<영상 id>?t=<초>" 부분. 영상 id가 틀리면 null, 시각이 없거나 틀리면 0초.
export function parseClipParam(param: string | null): ClipTarget | null {
  if (!param) return null;
  const [id, query = ''] = param.split('?', 2);
  if (!VIDEO_ID.test(id)) return null;
  const raw = new URLSearchParams(query).get('t');
  const t = raw === null ? 0 : Number(raw);
  return { videoId: id, t: Number.isFinite(t) && t >= 0 ? t : 0 };
}

// 앱 안에서 열었을 때만 닫기가 history.back()으로 돌아간다. 딥링크로 바로 열면 앱 밖으로 나가지 않게 클립 탭으로 간다.
let openedFromApp = false;

export function openClip(videoId: string, t: number): void {
  openedFromApp = true;
  window.location.hash = clipHash(videoId, t);
}

export function closeClip(): void {
  if (openedFromApp) {
    openedFromApp = false;
    window.history.back();
  } else {
    go('feed', true);
  }
}
