import { describe, expect, test } from 'bun:test';
import type { Wordbook } from './api';
import { practiceWordsFor, type CallSetup } from './setup';

const BOOK: Wordbook = {
  words: Array.from({ length: 10 }, (_, i) => ({ lemma: `word${i}`, gloss: '뜻' })),
  phrases: [],
};
const LOOKED_UP = [{ lemma: 'mitigate', gloss: '완화하다', source: 'lookup' }];

describe('practice words for a call', () => {
  test('a friend call uses up to eight wordbook words', () => {
    const setup: CallSetup = { kind: 'smalltalk', partner: 'jake' };
    expect(practiceWordsFor(setup, LOOKED_UP, BOOK).map((w) => w.lemma)).toEqual(BOOK.words.slice(0, 8).map((w) => w.lemma));
  });

  test('without a wordbook, or with sharing off, the looked-up words stay', () => {
    const setup: CallSetup = { kind: 'smalltalk', partner: 'jake' };
    expect(practiceWordsFor(setup, LOOKED_UP, null)).toBe(LOOKED_UP);
    expect(practiceWordsFor(setup, LOOKED_UP, { words: [], phrases: [] })).toBe(LOOKED_UP);
  });

  test('Ms. Park keeps her own words and Teach-back gets none', () => {
    expect(practiceWordsFor({ kind: 'freetalk', topic: '' }, LOOKED_UP, BOOK)).toBe(LOOKED_UP);
    expect(practiceWordsFor({ kind: 'teachback', lessonDate: '2026-10-21', sections: [], seniorMode: 'during' }, LOOKED_UP, BOOK)).toEqual([]);
  });
});
