import { describe, expect, test } from 'bun:test';
import { exampleLabel, nextExample } from './examples';

describe('nextExample', () => {
  test('다음 위치를 돌려준다', () => {
    expect(nextExample(0, 3)).toBe(1);
    expect(nextExample(1, 3)).toBe(2);
  });

  test('마지막이거나 범위 밖이면 null이다(처음으로 돌아가지 않는다)', () => {
    expect(nextExample(2, 3)).toBeNull();
    expect(nextExample(0, 1)).toBeNull();
    expect(nextExample(-1, 3)).toBeNull();
    expect(nextExample(5, 3)).toBeNull();
  });
});

describe('exampleLabel', () => {
  test('몇 번째인지 보인다', () => {
    expect(exampleLabel(0, 3)).toBe('1/3');
    expect(exampleLabel(2, 3)).toBe('3/3');
  });

  test('하나뿐이거나 범위 밖이면 비어 있다', () => {
    expect(exampleLabel(0, 1)).toBe('');
    expect(exampleLabel(-1, 3)).toBe('');
    expect(exampleLabel(3, 3)).toBe('');
  });
});
