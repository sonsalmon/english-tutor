import { describe, expect, test } from 'bun:test';
import { extendRange, findUnits, isSingleWord, lookupForm, MAX_PHRASE_WORDS, wordCount } from './units';

const slice = (text: string, m: { index: number; length: number }) => text.slice(m.index, m.index + m.length);

describe('findUnits', () => {
  test('두 낱말 표현이 한 조각으로 나온다', () => {
    const text = 'I got a short shift today';
    const found = findUnits(text, [{ text: 'short shift', gloss: '단축 근무' }]);
    expect(found.map((m) => slice(text, m))).toEqual(['short shift']);
    expect(found[0].unit.gloss).toBe('단축 근무');
  });

  test('대소문자와 여러 칸 공백을 무시한다', () => {
    const text = 'They PUT   OFF the meeting. Then Short\n shift.';
    const found = findUnits(text, [{ text: 'put off' }, { text: 'short shift' }]);
    expect(found.map((m) => slice(text, m))).toEqual(['PUT   OFF', 'Short\n shift']);
  });

  test('낱말 일부에는 맞지 않는다', () => {
    expect(findUnits('two short shifts', [{ text: 'short shift' }])).toEqual([]);
    expect(findUnits('a short shift2', [{ text: 'short shift' }])).toEqual([]);
    expect(findUnits('ashort shift', [{ text: 'short shift' }])).toEqual([]);
  });

  test('겹치는 구는 긴 쪽이 이긴다', () => {
    const text = 'Please put off the meeting';
    const found = findUnits(text, [{ text: 'put off' }, { text: 'off the meeting' }, { text: 'put off the meeting' }]);
    expect(found.map((m) => slice(text, m))).toEqual(['put off the meeting']);
  });

  test('겹치지 않는 구는 둘 다 남고 앞에서 뒤 순서다', () => {
    const text = 'short shift then put off';
    const found = findUnits(text, [{ text: 'put off' }, { text: 'short shift' }]);
    expect(found.map((m) => slice(text, m))).toEqual(['short shift', 'put off']);
  });

  test('구가 없거나 낱말 하나뿐이면 아무것도 찾지 않는다', () => {
    expect(findUnits('hello world', undefined)).toEqual([]);
    expect(findUnits('hello world', [])).toEqual([]);
    expect(findUnits('hello world', [{ text: 'hello' }, { text: '' }])).toEqual([]);
    expect(findUnits('hello world', [{ text: 'nope nope' }])).toEqual([]);
  });

  test("아포스트로피 모양이 달라도 같은 표현이다", () => {
    const text = 'I can’t stand it';
    expect(findUnits(text, [{ text: "can't stand" }]).map((m) => slice(text, m))).toEqual(['can’t stand']);
  });
});

describe('extendRange', () => {
  const text = 'He said: put off, then short shift now.';

  test('뒤 단어를 붙인다', () => {
    const start = text.indexOf('short');
    expect(extendRange(text, { start, end: start + 5 }, 'after')).toEqual({ start, end: start + 11 });
  });

  test('앞 단어를 붙인다', () => {
    const start = text.indexOf('shift');
    const range = extendRange(text, { start, end: start + 5 }, 'before');
    expect(range && text.slice(range.start, range.end)).toBe('short shift');
  });

  test('문장부호를 넘지 않는다', () => {
    const start = text.indexOf('put');
    expect(extendRange(text, { start, end: start + 3 }, 'before')).toBeNull();
    const off = text.indexOf('off');
    expect(extendRange(text, { start: start, end: off + 3 }, 'after')).toBeNull();
  });

  test(`최대 ${MAX_PHRASE_WORDS}낱말까지만 넓힌다`, () => {
    const t = 'one two three four five';
    expect(extendRange(t, { start: 0, end: 'one two three'.length }, 'after')).toEqual({ start: 0, end: 'one two three four'.length });
    expect(extendRange(t, { start: 0, end: 'one two three four'.length }, 'after')).toBeNull();
  });
});

describe('낱말 규칙', () => {
  test('lookupForm은 끝의 하이픈과 따옴표를 떼고 길이를 본다', () => {
    expect(lookupForm("don't")).toBe("don't");
    expect(lookupForm("rock-")).toBe('rock');
    expect(lookupForm('a')).toBeNull();
  });

  test('낱말 수와 한 낱말 판정', () => {
    expect(wordCount('short shift')).toBe(2);
    expect(wordCount('')).toBe(0);
    expect(isSingleWord('shift')).toBe(true);
    expect(isSingleWord('short shift')).toBe(false);
  });
});
