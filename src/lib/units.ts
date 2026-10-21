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

// 끝의 하이픈과 따옴표를 떼고 2~64자인 낱말만 사전에 묻는다(WordText와 StarButton이 같은 규칙을 쓴다).
export function lookupForm(token: string): string | null {
  const word = token.replace(/’/g, "'").replace(/[-']+$/, '');
  return word.length >= 2 && word.length <= 64 ? word : null;
}

export const isSingleWord = (text: string): boolean => /^[A-Za-z][A-Za-z'’-]*$/.test(text.trim());
