import { describe, expect, test } from 'bun:test';
import { rememberSeen } from './apiFeed';
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
