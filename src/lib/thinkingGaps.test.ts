import { describe, expect, test } from 'bun:test';
import { toThinkingGaps } from './thinkingGaps';

const base = { korean: '정신없다', english: "I'm swamped", kind: 'framing', note: '일에 잠긴 이미지예요.' };

describe('toThinkingGaps', () => {
  test('old items without detail and examples keep only the original fields', () => {
    expect(toThinkingGaps([base])).toEqual([base]);
  });

  test('keeps trimmed detail and at most two string examples', () => {
    const [gap] = toThinkingGaps([{ ...base, detail: ' 자세한 설명 ', examples: [' One. ', 3, '', 'Two.', 'Three.'] }]);
    expect(gap.detail).toBe('자세한 설명');
    expect(gap.examples).toEqual(['One.', 'Two.']);
  });

  test('drops bad detail and example types without dropping the item', () => {
    const [gap] = toThinkingGaps([{ ...base, detail: 7, examples: 'nope' }]);
    expect(gap).toEqual(base);
    expect(toThinkingGaps([{ ...base, detail: '  ', examples: [null, ' '] }])[0]).toEqual(base);
  });

  test('drops items with a wrong kind or non-string korean and english', () => {
    expect(toThinkingGaps([null, 'x', { ...base, kind: 'grammar' }, { ...base, korean: 1 }, { ...base, english: undefined }])).toEqual([]);
    expect(toThinkingGaps(undefined)).toEqual([]);
  });

  test('missing note becomes an empty string', () => {
    expect(toThinkingGaps([{ korean: 'k', english: 'e', kind: 'word' }])[0].note).toBe('');
  });
});
