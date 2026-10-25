import { describe, expect, test } from 'bun:test';
import { parseAccentKey } from './api';

describe('parseAccentKey', () => {
  test('keeps a well-formed key as it is', () => {
    const key = parseAccentKey({
      source_date: '2026-10-20',
      habits: [{ id: 'b_v:vote', label: 'b / v', meant: 'vote', heard_as: 'boat', count: 1, total: 1, strength: 'strong', action: 'practice', tip: 't', examples: [{ meant_text: 'We took the vote.', heard_text: 'We took the boat.' }] }],
      words: [{ id: 'boat>vote', heard: 'boat', intended: 'vote', count: 3, action: 'adjust', last_seen: '2026-10-21T10:00:00+09:00' }],
    });
    expect(key.habits[0]).toMatchObject({ id: 'b_v:vote', action: 'practice', strength: 'strong' });
    expect(key.habits[0].examples).toEqual([{ meant_text: 'We took the vote.', heard_text: 'We took the boat.' }]);
    expect(key.words[0]).toMatchObject({ id: 'boat>vote', count: 3, action: 'adjust' });
  });

  test('broken data gives an empty key, and odd entries are dropped or defaulted', () => {
    expect(parseAccentKey(null)).toEqual({ source_date: '', habits: [], words: [] });
    expect(parseAccentKey({ habits: 'x', words: 5 })).toEqual({ source_date: '', habits: [], words: [] });
    const key = parseAccentKey({ habits: [{ id: 'a:b', meant: 'b', heard_as: 'a', strength: 'weird', action: 'weird', examples: [{ heard_text: '' }, 'x'] }, { id: 1 }], words: [{ id: 'x>y', heard: 'x', intended: 'y' }, {}] });
    expect(key.habits).toHaveLength(1);
    expect(key.habits[0]).toMatchObject({ strength: 'slight', action: 'adjust', count: 0, examples: [] });
    expect(key.words).toEqual([{ id: 'x>y', heard: 'x', intended: 'y', count: 1, action: 'adjust', last_seen: '' }]);
  });
});
