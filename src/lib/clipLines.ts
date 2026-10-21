import type { ClipLine, ClipSegments, SaveSource } from './api';

// 시각 time에 해당하는 줄의 위치: start가 time 이하인 마지막 줄. 첫 줄보다 앞이면 -1, 줄 사이 틈이면 앞 줄, 마지막 줄 뒤면 마지막 줄.
export function lineIndexAt(lines: readonly ClipLine[], time: number): number {
  let lo = 0;
  let hi = lines.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (lines[mid].start <= time) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return found;
}

export function indexOfId(lines: readonly ClipLine[], id: number | null | undefined): number {
  return id == null ? -1 : lines.findIndex((l) => l.id === id);
}

// 사용자가 줄 목록을 직접 움직인 뒤 pauseMs 동안은 목록이 현재 줄을 따라 스스로 움직이지 않는다.
export function canAutoScroll(now: number, lastUserScrollAt: number, pauseMs: number): boolean {
  return now - lastUserScrollAt >= pauseMs;
}

// 위나 아래로 더 불러온 창을 지금 줄 목록에 합친다. 줄 id는 영상 안에서 유일하므로 같은 id는 한 번만 남기고 시간 순으로 세운다.
// 더 있는지는 불러온 쪽의 답을 따르고, 반대쪽은 그대로 둔다. atId(지금 줄)는 바꾸지 않는다.
export function mergeSegments(prev: ClipSegments, next: ClipSegments, side: 'before' | 'after'): ClipSegments {
  const known = new Set(prev.lines.map((l) => l.id));
  const lines = [...prev.lines, ...next.lines.filter((l) => !known.has(l.id))].sort((a, b) => a.start - b.start || a.id - b.id);
  return {
    ...prev,
    lines,
    hasMoreBefore: side === 'before' ? next.hasMoreBefore : prev.hasMoreBefore,
    hasMoreAfter: side === 'after' ? next.hasMoreAfter : prev.hasMoreAfter,
  };
}

// 이 줄에서 저장한 단어·표현에 붙일 출처: 영상 ID, 줄 시작 초(내림), 영상 제목.
export function lineSource(videoId: string, title: string, line: ClipLine): SaveSource {
  return { video_id: videoId, t: Math.max(0, Math.floor(line.start)), title };
}
