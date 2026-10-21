import { describe, expect, test } from 'bun:test';
import { cleanLearnerText } from './transcript';

// server/test_transcript_clean.py가 같은 표를 쓴다. 한쪽을 고치면 다른 쪽도 고친다.
const CASES: [string, string][] = [
  ['嗯', '(mm)'],
  ['嗯嗯嗯', '(mm)'],
  ['呃…', '(mm)'],
  ['こんにちは', '(mm)'],
  ['嗯'.repeat(12), '(mm)'],
  ['嗯'.repeat(13), '(unclear)'],
  ['嗯 I think', 'I think'],
  ['我想去 the store', 'the store'],
  ['嗯 음 hello', '음 hello'],
  ['음', '음'],
  ['mm', 'mm'],
  ['I think so', 'I think so'],
  ['(mm)', '(mm)'],
  ['', ''],
];

describe('cleanLearnerText', () => {
  test.each(CASES)('%j -> %j', (text, expected) => {
    expect(cleanLearnerText(text)).toBe(expected);
  });
});
