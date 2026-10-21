export function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

export function yesterdayOf(now: Date): Date {
  const d = new Date(now);
  d.setDate(d.getDate() - 1);
  return d;
}

export function clock(d: Date): string {
  return d.toLocaleTimeString('ko-KR', { hour: 'numeric', minute: '2-digit' });
}

// 목록 오른쪽 시각: 오늘은 시각, 어제는 "어제", 그 밖에는 "10월 20일".
export function listTime(at: string | null | undefined, now = new Date()): string {
  if (!at) return '';
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  if (sameDay(d, now)) return clock(d);
  if (sameDay(d, yesterdayOf(now))) return '어제';
  return d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' });
}

// 전문 머리글의 "2026-10-20 21:03"을 "10월 20일 21:03"으로.
export function formatWhen(startedAt: string): string {
  const [date, time] = startedAt.split(' ');
  const [, month, day] = date.split('-').map(Number);
  return `${month}월 ${day}일 ${time}`;
}

export function formatDuration(sec: number): string {
  const minutes = Math.floor(sec / 60);
  const seconds = sec % 60;
  return minutes > 0 ? `${minutes}분 ${seconds}초` : `${seconds}초`;
}

// 사람 페이지의 한 줄 "4분"처럼 초는 버린다. 1분 미만은 초로 보인다.
export function formatShortDuration(sec: number): string {
  return sec >= 60 ? `${Math.floor(sec / 60)}분` : `${sec}초`;
}
