import { afterEach, describe, expect, test } from 'bun:test';
import { parseNative, rememberSeen, reportBlockedVideo, sayLine } from './apiFeed';
import { filterWordbook } from './apiWords';

describe('seen clip memory', () => {
  test('keeps only the newest ids up to the cap', () => {
    const list = Array.from({ length: 200 }, (_, i) => `v${i}:0`);
    const next = rememberSeen(list, ['new:1', 'new:2'], 200);

    expect(next.length).toBe(200);
    expect(next.slice(-2)).toEqual(['new:1', 'new:2']);
    expect(next).not.toContain('v0:0');
    expect(next).not.toContain('v1:0');
  });

  test('a repeated id moves to the end instead of doubling', () => {
    expect(rememberSeen(['a:1', 'b:2', 'c:3'], ['a:1'])).toEqual(['b:2', 'c:3', 'a:1']);
  });
});

describe('native expression payload', () => {
  test('a full payload is kept and numbers are coerced', () => {
    const info = parseNative({ expression: 'end up', kind: 'phrasal_verb', meaning_ko: '결국 ~하게 되다', why_hard: 'x', register: 'casual', example: 'We ended up home.', per_million: '121.3' });
    expect(info?.expression).toBe('end up');
    expect(info?.per_million).toBeCloseTo(121.3);
  });

  test('say_ko is trimmed, capped at 40 characters and optional', () => {
    const base = { expression: 'end up', kind: 'phrasal_verb', meaning_ko: '결국 ~하게 되다' };
    expect(parseNative({ ...base, say_ko: '  결국 집에 갔어  ' })?.say_ko).toBe('결국 집에 갔어');
    expect(parseNative({ ...base, say_ko: '가'.repeat(60) })?.say_ko.length).toBe(40);
    expect(parseNative(base)?.say_ko).toBe('');
  });

  test('the Korean line falls back from say_ko to the first meaning to the dictionary gloss', () => {
    const info = parseNative({ expression: 'come up with', kind: 'phrasal_verb', meaning_ko: '떠올리다, 생각해 내다', say_ko: '좋은 생각이 났어' });
    expect(sayLine(info)).toBe('좋은 생각이 났어');
    expect(sayLine(info && { ...info, say_ko: '' })).toBe('떠올리다');
    expect(sayLine(null, ' 아이디어를 내다 ')).toBe('아이디어를 내다');
    expect(sayLine(null)).toBe('');
  });

  test('missing expression or meaning is rejected', () => {
    expect(parseNative({ expression: 'end up' })).toBeNull();
    expect(parseNative({ meaning_ko: '뜻' })).toBeNull();
    expect(parseNative(null)).toBeNull();
  });
});

describe('wordbook search', () => {
  const items = [
    { lemma: 'put off', gloss: '미루다' },
    { lemma: 'cutting board', gloss: '도마' },
  ];
  const textOf = (i: { lemma: string }) => i.lemma;

  test('matches the English text or the Korean meaning, ignoring case and spaces around', () => {
    expect(filterWordbook(items, '  PUT ', textOf)).toEqual([items[0]]);
    expect(filterWordbook(items, '도마', textOf)).toEqual([items[1]]);
  });

  test('empty query keeps everything and no match gives an empty list', () => {
    expect(filterWordbook(items, '   ', textOf)).toEqual(items);
    expect(filterWordbook(items, 'zzz', textOf)).toEqual([]);
  });
});

describe('reporting a video the player could not embed', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  test('posts the video id as JSON to the blocked endpoint', async () => {
    const calls: { url: string; init: RequestInit }[] = [];
    globalThis.fetch = (async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response('{"status":"ok"}', { status: 200 });
    }) as unknown as typeof fetch;

    expect(await reportBlockedVideo('abc12345678')).toBe(true);

    expect(calls.length).toBe(1);
    expect(calls[0].url).toBe('/api/clips/blocked');
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ video_id: 'abc12345678' });
    expect(new Headers(calls[0].init.headers).get('content-type')).toBe('application/json');
  });

  test('a rejected request or an error status is reported as false and never throws', async () => {
    globalThis.fetch = (async () => new Response('{}', { status: 400 })) as unknown as typeof fetch;
    expect(await reportBlockedVideo('abc12345678')).toBe(false);

    globalThis.fetch = (async () => {
      throw new TypeError('offline');
    }) as unknown as typeof fetch;
    expect(await reportBlockedVideo('abc12345678')).toBe(false);
  });
});
