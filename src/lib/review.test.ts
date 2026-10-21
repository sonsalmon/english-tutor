import { afterEach, describe, expect, test } from 'bun:test';
import { finishReview, flagReview, getPhraseClips, getReview, isFlagged, reviewKey, textKey, withState } from './review';

const realFetch = globalThis.fetch;
type Call = { url: string; init?: RequestInit };

function stubFetch(respond: (url: string) => Response): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = ((url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return Promise.resolve(respond(String(url)));
  }) as typeof fetch;
  return calls;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => {
  globalThis.fetch = realFetch;
});

describe('textKey / reviewKey (server known.make_key와 같은 입력표)', () => {
  const table: [string, string][] = [
    ['  Sorry?! ', 'sorry'],
    ['I\u2019m  SO   sorry.', "i'm so sorry"],
    ['한국어', ''],
    ['So, what do you do?', 'so what do you do'],
    ['Thanks for jumping on this!', 'thanks for jumping on this'],
  ];
  for (const [input, key] of table) {
    test(JSON.stringify(input), () => expect(textKey(input)).toBe(key));
  }

  test('reviewKey는 종류와 정리한 글을 콜론으로 잇는다', () => {
    expect(reviewKey('correction', 'I just started.')).toBe('correction:i just started');
    expect(reviewKey('us_style', 'So, what do you do?')).toBe('us_style:so what do you do');
  });
});

describe('withState / isFlagged', () => {
  test('상태를 넣고 null이면 지우며 원본은 바꾸지 않는다', () => {
    const base = { 'vocab:a b': 'saved' as const };
    const next = withState(base, 'correction:x y', 'known');
    expect(next).toEqual({ 'vocab:a b': 'saved', 'correction:x y': 'known' });
    expect(base).toEqual({ 'vocab:a b': 'saved' });
    expect(withState(next, 'correction:x y', null)).toEqual(base);
    expect(withState(next, 'vocab:a b', undefined)).toEqual({ 'correction:x y': 'known' });
  });

  test('known과 misheard만 표시된 것으로 본다', () => {
    expect(['known', 'misheard', 'saved', undefined].map((s) => isFlagged(s as never))).toEqual([true, true, false, false]);
  });
});

describe('서버 호출', () => {
  test('getReview는 알려진 상태만 담는다', async () => {
    const calls = stubFetch(() => json({ items: { 'correction:a b': 'known', 'vocab:c d': 'weird', 'good:e f': 5, 'us_style:g h': 'saved' } }));
    expect(await getReview('2026-10-20-090000')).toEqual({ 'correction:a b': 'known', 'us_style:g h': 'saved' });
    expect(calls[0].url).toBe('/api/calls/2026-10-20-090000/review');
  });

  test('getReview는 실패하면 던지고 본문이 이상하면 빈 객체', async () => {
    stubFetch(() => json({ detail: 'x' }, 400));
    await expect(getReview('s')).rejects.toThrow('x');
    stubFetch(() => json({ items: 'nope' }));
    expect(await getReview('s')).toEqual({});
  });

  test('flagReview는 stem·kind·text·state를 JSON으로 보내고 실패하면 던진다', async () => {
    const calls = stubFetch(() => json({ status: 'ok' }));
    await flagReview({ stem: '2026-10-20-090000', kind: 'correction', text: 'I just started', state: 'misheard' });
    expect(calls[0].url).toBe('/api/review/flag');
    expect(calls[0].init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ stem: '2026-10-20-090000', kind: 'correction', text: 'I just started', state: 'misheard' });
    stubFetch(() => json({ detail: '틀렸어요' }, 400));
    await expect(flagReview({ stem: 's', kind: 'vocab', text: 'x y', state: null })).rejects.toThrow('틀렸어요');
  });

  test('finishReview는 keepalive로 빈 JSON을 보내고 실패해도 던지지 않는다', async () => {
    const calls = stubFetch(() => json({ status: 'scheduled' }));
    finishReview('2026-10-20-090000');
    expect(calls[0].url).toBe('/api/calls/2026-10-20-090000/review/finish');
    expect(calls[0].init?.keepalive).toBe(true);
    expect(calls[0].init?.body).toBe('{}');
    globalThis.fetch = (() => Promise.reject(new Error('offline'))) as typeof fetch;
    expect(() => finishReview('s')).not.toThrow();
  });

  test('getPhraseClips는 표현을 주소에 넣고 상태를 정리한다', async () => {
    const clip = { id: 'abc', title: 'T', channel: 'C', thumbnail: '', start: 12, text: 'so what do you do', source: 'db' };
    const calls = stubFetch(() => json({ status: 'ok', clips: [clip] }));
    expect(await getPhraseClips('So, what do you do?', 3)).toEqual({ status: 'ok', clips: [clip] });
    expect(calls[0].url).toBe('/api/clips/phrase?q=So%2C%20what%20do%20you%20do%3F&limit=3');
    stubFetch(() => json({ status: 'no_db', clips: [] }));
    expect((await getPhraseClips('x y')).status).toBe('no_db');
    stubFetch(() => json({ status: 'something', clips: 'junk' }));
    expect(await getPhraseClips('x y')).toEqual({ status: 'no_query', clips: [] });
  });
});
