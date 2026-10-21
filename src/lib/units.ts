// 두 낱말 이상으로 이루어진 표현(구동사, 숙어)을 문장 안에서 찾고, 낱말 단위 팝오버를 구 단위로 넓히는 규칙.

export type Unit = { text: string; gloss?: string };
export type UnitMatch = { index: number; length: number; unit: Unit };
export type Range = { start: number; end: number };

export const WORD_TOKEN = /[A-Za-z][A-Za-z'’-]*/g;
export const MAX_PHRASE_WORDS = 4;

const ALNUM = /[A-Za-z0-9]/;

export function wordCount(text: string): number {
  return text.match(WORD_TOKEN)?.length ?? 0;
}

// 대소문자는 무시하고, 공백은 몇 칸이든 하나로 본다. 낱말 일부(shifts 안의 shift)에는 맞지 않는다.
function patternOf(text: string): RegExp | null {
  const words = text.match(WORD_TOKEN);
  if (!words || words.length < 2) return null;
  const body = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/[’']/g, "['’]")).join('\\s+');
  return new RegExp(body, 'gi');
}

export function findUnits(text: string, units: Unit[] | undefined): UnitMatch[] {
  if (!units?.length) return [];
  const found: UnitMatch[] = [];
  for (const unit of units) {
    const pattern = patternOf(unit.text);
    if (!pattern) continue;
    for (const m of text.matchAll(pattern)) {
      const before = text[m.index - 1];
      const after = text[m.index + m[0].length];
      if ((before && ALNUM.test(before)) || (after && ALNUM.test(after))) continue;
      found.push({ index: m.index, length: m[0].length, unit });
    }
  }
  // 겹치면 긴 구가 이긴다. 길이가 같으면 앞선 것이 이긴다.
  found.sort((a, b) => b.length - a.length || a.index - b.index);
  const taken: UnitMatch[] = [];
  for (const f of found) {
    if (taken.every((t) => f.index + f.length <= t.index || f.index >= t.index + t.length)) taken.push(f);
  }
  return taken.sort((a, b) => a.index - b.index);
}

// 구 범위를 이웃 낱말까지 넓힌다. 사이에 공백만 있을 때만 붙이고, 문장부호를 넘지 않으며, 최대 MAX_PHRASE_WORDS 낱말까지.
export function extendRange(text: string, range: Range, side: 'before' | 'after'): Range | null {
  if (wordCount(text.slice(range.start, range.end)) >= MAX_PHRASE_WORDS) return null;
  if (side === 'after') {
    const m = /^\s+([A-Za-z][A-Za-z'’-]*)/.exec(text.slice(range.end));
    if (!m) return null;
    return { start: range.start, end: range.end + m[0].length };
  }
  const m = /([A-Za-z][A-Za-z'’-]*)\s+$/.exec(text.slice(0, range.start));
  if (!m) return null;
  return { start: range.start - m[0].length, end: range.end };
}

const PLAIN_WORDS = /^[A-Za-z][A-Za-z'’-]*(?:\s+[A-Za-z][A-Za-z'’-]*)*$/;

// 이어 탭한 두 범위를 하나로 묶는다. 사이에 낱말과 공백만 있고(문장부호 없음) 낱말이 MAX_PHRASE_WORDS 이하일 때만, 아니면 null.
export function joinRanges(text: string, a: Range, b: Range): Range | null {
  const range = { start: Math.min(a.start, b.start), end: Math.max(a.end, b.end) };
  const body = text.slice(range.start, range.end);
  return PLAIN_WORDS.test(body) && wordCount(body) <= MAX_PHRASE_WORDS ? range : null;
}

// 구로 묶기 모드에서 낱말을 탭할 때 고른 범위가 어떻게 바뀌는지. 같은 곳을 다시 탭하면 해제, 이미 고른 범위 안을 탭하면 그 낱말부터 다시,
// 이어 붙일 수 없는 곳을 탭하면 그 낱말부터 다시 고른다.
export function pickRange(text: string, current: Range | null, tapped: Range): Range | null {
  if (!current) return tapped;
  if (current.start === tapped.start && current.end === tapped.end) return null;
  if (tapped.start >= current.start && tapped.end <= current.end) return tapped;
  return joinRanges(text, current, tapped) ?? tapped;
}

export const MAX_CANDIDATES = 40;

// 문장 안에서 이어진(공백만 사이에 있는) 2~MAX_PHRASE_WORDS 낱말 조합. 저장했는지 서버에 한꺼번에 물을 글(소문자, 공백 하나)이다.
// 서버가 한 번에 받는 40개를 넘지 않게 앞에서부터 자른다.
export function phraseCandidates(text: string): string[] {
  const words = [...text.matchAll(WORD_TOKEN)].map((m) => ({ start: m.index, end: m.index + m[0].length, word: m[0].toLowerCase() }));
  const found = new Set<string>();
  for (let i = 0; i < words.length; i++) {
    const parts = [words[i].word];
    for (let j = i + 1; j < words.length && parts.length < MAX_PHRASE_WORDS; j++) {
      if (!/^\s+$/.test(text.slice(words[j - 1].end, words[j].start))) break;
      parts.push(words[j].word);
      found.add(parts.join(' '));
      if (found.size >= MAX_CANDIDATES) return [...found];
    }
  }
  return [...found];
}

// 끝의 하이픈과 따옴표를 떼고 2~64자인 낱말만 사전에 묻는다(WordText와 StarButton이 같은 규칙을 쓴다).
export function lookupForm(token: string): string | null {
  const word = token.replace(/’/g, "'").replace(/[-']+$/, '');
  return word.length >= 2 && word.length <= 64 ? word : null;
}

export const isSingleWord = (text: string): boolean => /^[A-Za-z][A-Za-z'’-]*$/.test(text.trim());
