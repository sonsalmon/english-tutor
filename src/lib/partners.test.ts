import { describe, expect, test } from 'bun:test';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { PartnerMemory } from './api';
import { buildChatInstruction, freeTalkInstruction, PARTNER_PROMPT_LIMIT, smallTalkInstruction } from './instructions';
import { PARTNERS, partnerById } from './partners';

const brian = partnerById('brian');
const OTHERS = PARTNERS.filter((p) => p.id !== 'brian');

const FULL_MEMORY: PartnerMemory = {
  partner: 'brian',
  updated: '2026-10-21',
  facts: Array.from({ length: 12 }, (_, i) => ({ text: `Fact ${i} `.padEnd(120, 'x'), last_seen: '2026-10-20' })),
  threads: Array.from({ length: 5 }, (_, i) => ({ text: `Thread ${i} `.padEnd(80, 'y'), ko: '이어갈 일', last_seen: '2026-10-20' })),
  self_story: Array.from({ length: 8 }, (_, i) => ({ story: `Story ${i}`, progress: `Told beat ${i} `.padEnd(160, 'z'), last_seen: '2026-10-20' })),
  jokes: Array.from({ length: 5 }, (_, i) => ({ text: `Joke ${i} `.padEnd(100, 'j'), last_seen: '2026-10-20' })),
  episodes: Array.from({ length: 12 }, (_, i) => ({ date: '2026-10-20', mode: 'call' as const, summary: `Episode ${i} `.padEnd(200, 'e') })),
};

describe('Brian', () => {
  test('is registered with its own voice and portrait file', () => {
    expect(brian.id).toBe('brian');
    expect(brian.voice).toBe('Achird');
    expect(OTHERS.map((p) => p.voice)).not.toContain('Achird');
    expect(brian.portrait).toBe('/partners/brian.webp');
    expect(existsSync(join(import.meta.dir, '../../public', brian.portrait))).toBe(true);
  });

  test('all partner ids and voices are unique', () => {
    const ids = PARTNERS.map((p) => p.id);
    const voices = PARTNERS.map((p) => p.voice);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(voices).size).toBe(voices.length);
  });

  test('call and chat prompts carry the section markers and stay under the limit', () => {
    const calls = [smallTalkInstruction('', [], brian, [], null, ''), freeTalkInstruction('', '', null, [], brian, [], null)];
    for (const text of calls) {
      expect(text).toContain('FAITH LIFE');
      expect(text).toContain('IDENTITY & SOUL');
      expect(text).toContain('VOICE & DELIVERY');
      expect(text).not.toContain('TEXTING STYLE');
      expect(text.length).toBeLessThanOrEqual(PARTNER_PROMPT_LIMIT);
    }
    for (const memory of [null, FULL_MEMORY]) {
      const chat = buildChatInstruction(brian, '', memory);
      expect(chat).toContain('FAITH LIFE');
      expect(chat).toContain('TEXTING STYLE');
      expect(chat).not.toContain('VOICE & DELIVERY');
      expect(chat).not.toContain('CALL START & END');
      expect(chat.length).toBeLessThanOrEqual(PARTNER_PROMPT_LIMIT);
    }
  });

  test('a full memory trims the STORY BANK to four stories and keeps its marker', () => {
    // CALL FLOW의 '1. OPENING' 줄에도 첫 화제 이야기(Beat 1 포함)가 들어가므로 STORY BANK 줄만 센다.
    const storyCount = (text: string) => text.split('\n').filter((l) => /^\d+\.\s/.test(l) && l.includes('Beat 1') && !l.includes('OPENING')).length;
    const light = smallTalkInstruction('', [], brian, [], null, '');
    const full = freeTalkInstruction('', '', null, [], brian, [], FULL_MEMORY);
    expect(light).toContain('STORY BANK (Brian)');
    expect(storyCount(light)).toBe(9);
    expect(full).toContain('STORY BANK (Brian)');
    expect(storyCount(full)).toBe(4);
  });
});
