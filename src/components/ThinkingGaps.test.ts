import { describe, expect, test } from 'bun:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Tutoring } from '../lib/api';
import { ThinkingGaps } from './ThinkingGaps';

const tutoring = {
  corrections: [],
  good: [],
  vocab: [],
  pragmatics: [],
  thinking_gaps: [{ korean: '정신없다', english: "I'm swamped", kind: 'framing', note: '일에 잠긴 이미지예요.' }],
} as unknown as Tutoring;

describe('ThinkingGaps row header', () => {
  test('is one button with no button nested inside, so a tap on the English phrase opens the row', () => {
    const html = renderToStaticMarkup(createElement(ThinkingGaps, { tutoring, stem: null }));
    expect(html).toContain("I&#x27;m swamped");
    const opens = [...html.matchAll(/<button\b/g)].map((m) => m.index!);
    expect(opens.length).toBe(1);
    for (const at of opens) {
      const close = html.indexOf('</button>', at);
      expect(html.slice(at + 1, close)).not.toContain('<button');
    }
  });
});
