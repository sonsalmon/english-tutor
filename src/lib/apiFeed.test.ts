import { describe, expect, test } from 'bun:test';
import { parseNative, rememberSeen } from './apiFeed';
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
