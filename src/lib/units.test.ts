import { describe, expect, test } from 'bun:test';
import { extendRange, findUnits, isSingleWord, joinRanges, lookupForm, MAX_CANDIDATES, MAX_PHRASE_WORDS, phraseCandidates, pickRange, wordCount } from './units';

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

const at = (text: string, word: string) => {
  const start = text.indexOf(word);
  return { start, end: start + word.length };
};

describe('joinRanges', () => {
  const text = 'Oh, that is a piece of cake! Really';

  test('이어진 두 낱말을 하나로 묶는다(순서와 상관없이)', () => {
    const piece = at(text, 'piece');
    const cake = at(text, 'cake');
    const joined = joinRanges(text, piece, cake);
    expect(joined && text.slice(joined.start, joined.end)).toBe('piece of cake');
    expect(joinRanges(text, cake, piece)).toEqual(joined);
  });

  test('문장부호를 사이에 두면 묶지 않는다', () => {
    expect(joinRanges(text, at(text, 'Oh'), at(text, 'that'))).toBeNull();
    expect(joinRanges(text, at(text, 'cake'), at(text, 'Really'))).toBeNull();
  });

  test(`${MAX_PHRASE_WORDS}낱말을 넘으면 묶지 않는다`, () => {
    expect(joinRanges(text, at(text, 'that'), at(text, 'cake'))).toBeNull();
    const four = joinRanges(text, at(text, 'is'), at(text, 'of'));
    expect(four && text.slice(four.start, four.end)).toBe('is a piece of');
  });
});

describe('pickRange', () => {
  const text = 'Oh, that is a piece of cake! Really';
  const piece = at(text, 'piece');
  const of = at(text, 'of');
  const cake = at(text, 'cake');

  test('처음 탭은 그 낱말만 고른다', () => {
    expect(pickRange(text, null, piece)).toEqual(piece);
  });

  test('이어서 탭하면 범위가 넓어진다', () => {
    const two = pickRange(text, piece, of);
    expect(two && text.slice(two.start, two.end)).toBe('piece of');
    const three = pickRange(text, two, cake);
    expect(three && text.slice(three.start, three.end)).toBe('piece of cake');
  });

  test('같은 곳을 다시 탭하면 고른 것이 풀린다', () => {
    expect(pickRange(text, piece, piece)).toBeNull();
  });

  test('이미 고른 범위 안을 탭하면 그 낱말부터 다시 고른다', () => {
    const three = { start: piece.start, end: cake.end };
    expect(pickRange(text, three, of)).toEqual(of);
  });

  test('이어 붙일 수 없는 곳을 탭하면 그 낱말부터 다시 고른다', () => {
    expect(pickRange(text, piece, at(text, 'Really'))).toEqual(at(text, 'Really'));
    expect(pickRange(text, cake, at(text, 'Oh'))).toEqual(at(text, 'Oh'));
  });
});

describe('phraseCandidates', () => {
  test('이어진 2~4낱말 조합을 소문자·공백 하나로 모은다', () => {
    expect(phraseCandidates('A piece of  Cake')).toEqual(['a piece', 'a piece of', 'a piece of cake', 'piece of', 'piece of cake', 'of cake']);
  });

  test('문장부호에서 끊긴다', () => {
    expect(phraseCandidates('Oh, that is it. Fine')).toEqual(['that is', 'that is it', 'is it']);
  });

  test('낱말이 하나뿐이거나 비어 있으면 없다', () => {
    expect(phraseCandidates('Hello')).toEqual([]);
    expect(phraseCandidates('')).toEqual([]);
  });

  test(`서버가 받는 수(${MAX_CANDIDATES})를 넘기지 않는다`, () => {
    const long = Array.from({ length: 30 }, (_, i) => String.fromCharCode(97 + (i % 26)).repeat(2 + Math.floor(i / 26))).join(' ');
    expect(phraseCandidates(long).length).toBe(MAX_CANDIDATES);
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
