import { describe, expect, test } from 'bun:test';
import { orderPeople, previewOf, type PersonActivity } from './apiPeople';
import { PARTNERS } from './partners';
import { visiblePartners } from './visibility';

function activity(id: string, last_at: string | null, extra: Partial<PersonActivity> = {}): PersonActivity {
  return { id, last_call: null, last_message: null, call_count: 0, last_at, ...extra };
}

describe('orderPeople', () => {
  const shown = visiblePartners(false, PARTNERS);

  test('Ms. Park은 활동과 상관없이 맨 위, 친구는 마지막 활동이 최근인 순서', () => {
    const order = orderPeople(shown, [
      activity('park', '2026-10-21T09:00:00+09:00'),
      activity('jake', '2026-10-19T09:00:00+09:00'),
      activity('priya', '2026-10-20T21:00:00+09:00'),
      activity('brian', '2026-10-21T08:00:00+09:00'),
    ]).map((p) => p.id);
    expect(order).toEqual(['park', 'brian', 'priya', 'jake']);
  });

  test('활동이 없는 친구는 맨 아래에서 원래 순서를 지킨다', () => {
    const original = shown.filter((p) => p.id !== 'park').map((p) => p.id);
    const order = orderPeople(shown, []).map((p) => p.id);
    expect(order).toEqual(['park', ...original]);
    const mixed = orderPeople(shown, [activity('jake', '2026-10-20T09:00:00+09:00')]).map((p) => p.id);
    expect(mixed[1]).toBe('jake');
  });
});

describe('previewOf', () => {
  const call = { stem: '2026-10-20-210300', started_at: '2026-10-20 21:03', mission: 'Small Talk', duration_sec: 240 };

  test('통화도 채팅도 없으면 null', () => {
    expect(previewOf(undefined)).toBeNull();
    expect(previewOf(activity('jake', null))).toBeNull();
  });

  test('채팅이 통화보다 늦으면 채팅, 통화가 늦으면 통화', () => {
    const later = { role: 'me' as const, text: 'see you', at: '2026-10-20T22:00:00+09:00' };
    expect(previewOf(activity('jake', later.at, { last_call: call, last_message: later }))?.kind).toBe('message');
    const earlier = { ...later, at: '2026-10-20T20:00:00+09:00' };
    expect(previewOf(activity('jake', '2026-10-20T21:03:00+09:00', { last_call: call, last_message: earlier }))?.kind).toBe('call');
  });

  test('내가 보낸 메시지에는 "나: "가 붙는다', () => {
    const p = previewOf(activity('jake', 'x', { last_message: { role: 'me', text: 'hi', at: '2026-10-20T22:00:00+09:00' } }));
    expect(p?.text).toBe('나: hi');
  });
});
