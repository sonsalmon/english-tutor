import type { ClipLine, SaveSource } from './api';

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

// 이 줄에서 저장한 단어·표현에 붙일 출처: 영상 ID, 줄 시작 초(내림), 영상 제목.
export function lineSource(videoId: string, title: string, line: ClipLine): SaveSource {
  return { video_id: videoId, t: Math.max(0, Math.floor(line.start)), title };
}
