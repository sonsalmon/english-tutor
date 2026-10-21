import { withSummary, type CallSummary } from './api';
import { PARK_ID, isPark, type Partner } from './partners';

export type PersonCall = { stem: string; started_at: string; mission: string; duration_sec: number };
export type PersonMessage = { role: 'me' | 'friend'; text: string; at: string };
export type PersonActivity = {
  id: string;
  last_call: PersonCall | null;
  last_message: PersonMessage | null;
  call_count: number;
  last_at: string | null;
};

export async function getPeople(signal?: AbortSignal): Promise<PersonActivity[]> {
  const res = await fetch('/api/people', { signal });
  if (!res.ok) throw new Error('사람 목록을 불러오지 못했어요.');
  const data = await res.json();
  return Array.isArray(data?.people) ? data.people : [];
}

// partner=park는 친구 표시가 없는 통화(Ms. Park 통화와 옛 스몰토크)다.
export async function getPersonCalls(partnerId: string, limit = 50, signal?: AbortSignal): Promise<CallSummary[]> {
  const res = await fetch(`/api/calls?limit=${limit}&partner=${encodeURIComponent(partnerId)}`, { signal });
  if (!res.ok) throw new Error('통화 내역을 불러오지 못했어요.');
  const data = await res.json();
  return Array.isArray(data?.calls) ? data.calls.map(withSummary) : [];
}

function stamp(activity: PersonActivity | undefined): number {
  const t = new Date(activity?.last_at ?? '').getTime();
  return Number.isNaN(t) ? 0 : t;
}

// Ms. Park은 맨 위에 고정하고, 친구는 마지막 활동이 최근인 순서로. 활동이 같거나 없으면 원래 순서를 지킨다.
export function orderPeople(partners: Partner[], activity: PersonActivity[]): Partner[] {
  const byId = new Map(activity.map((a) => [a.id, a]));
  const park = partners.filter((p) => isPark(p) || p.id === PARK_ID);
  const friends = partners.filter((p) => !park.includes(p));
  const sorted = friends
    .map((p, index) => ({ p, index, at: stamp(byId.get(p.id)) }))
    .sort((a, b) => b.at - a.at || a.index - b.index)
    .map((x) => x.p);
  return [...park, ...sorted];
}

// 목록의 미리보기 한 줄: 채팅과 통화 중 더 늦은 쪽.
export type Preview = { kind: 'message' | 'call'; text: string; at: string | null } | null;

export function previewOf(activity: PersonActivity | undefined): Preview {
  if (!activity) return null;
  const { last_call: call, last_message: message } = activity;
  const callAt = call ? new Date(call.started_at.replace(' ', 'T') + '+09:00').getTime() : NaN;
  const messageAt = message ? new Date(message.at).getTime() : NaN;
  const useMessage = message && (!call || Number.isNaN(callAt) || (!Number.isNaN(messageAt) && messageAt >= callAt));
  if (useMessage && message) return { kind: 'message', text: `${message.role === 'me' ? '나: ' : ''}${message.text}`, at: message.at };
  if (call) {
    const minutes = Math.max(1, Math.round(call.duration_sec / 60));
    return { kind: 'call', text: `통화 ${minutes}분 · ${call.mission}`, at: activity.last_at };
  }
  return null;
}
