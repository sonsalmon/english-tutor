import type { ThinkingGap } from './api';

const MAX_EXAMPLES = 2;

// 서버 응답의 thinking_gaps를 화면 타입으로 정리한다. 옛 통화에는 detail·examples가 없으므로 없으면 키를 두지 않는다.
export function toThinkingGaps(value: unknown): ThinkingGap[] {
  if (!Array.isArray(value)) return [];
  const out: ThinkingGap[] = [];
  for (const g of value) {
    if (!g || typeof g !== 'object') continue;
    const r = g as Record<string, unknown>;
    if ((r.kind !== 'word' && r.kind !== 'framing') || typeof r.korean !== 'string' || typeof r.english !== 'string') continue;
    const gap: ThinkingGap = { korean: r.korean, english: r.english, kind: r.kind, note: typeof r.note === 'string' ? r.note : '' };
    if (typeof r.detail === 'string' && r.detail.trim()) gap.detail = r.detail.trim();
    const examples = (Array.isArray(r.examples) ? r.examples : [])
      .filter((e): e is string => typeof e === 'string' && !!e.trim())
      .map((e) => e.trim())
      .slice(0, MAX_EXAMPLES);
    if (examples.length) gap.examples = examples;
    out.push(gap);
  }
  return out;
}
