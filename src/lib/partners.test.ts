import { describe, expect, test } from 'bun:test';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import type { PartnerMemory } from './api';
import { buildChatInstruction, freeTalkInstruction, missionInstruction, PARTNER_PROMPT_LIMIT, smallTalkInstruction, SPEECH_STYLE } from './instructions';
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
    // 기억 v2는 사실 상한이 없다: 중요한 사실이 많이 쌓이면 한도(26000자)를 넘어 이야기 목록이 줄어든다.
    const keyFacts = Array.from({ length: 60 }, (_, i) => ({ text: `Key fact ${i} `.padEnd(120, 'k'), last_seen: '2026-10-20', importance: 5 }));
    const full = freeTalkInstruction('', '', null, [], brian, [], { ...FULL_MEMORY, facts: [...FULL_MEMORY.facts, ...keyFacts] });
    expect(light).toContain('STORY BANK (Brian)');
    expect(storyCount(light)).toBe(9);
    expect(full).toContain('STORY BANK (Brian)');
    expect(storyCount(full)).toBe(4);
  });
});

const FRIENDS = PARTNERS.filter((p) => p.id !== 'park');
const REMOVED_VARIETY = /(?<![\w])(Indian English|Kenyan English|Jordanian English|Canadian English|German-accented|Spanish-accented|Midwestern American English|ENGLISH VARIETY|na\?|yaar|arre|sasa|poa|pole pole|sawa|aki|yani|inshallah|wallah|vale|venga|claro|washroom|toque)(?![\w])/i;

describe('American friends', () => {
  test('every friend prompt (call, chat, persona fields) is free of the removed variety words', () => {
    for (const p of FRIENDS) {
      const texts = [
        p.persona, p.chatPersona, p.storyBank, p.intro, p.from,
        smallTalkInstruction('', [], p, [], null, ''),
        freeTalkInstruction('', '', null, [], p, [], null),
        buildChatInstruction(p, '', null),
      ];
      for (const text of texts) expect(REMOVED_VARIETY.test(text ?? '')).toBe(false);
    }
  });

  test('every friend is US-born with General American speech and a US city', () => {
    for (const p of FRIENDS) {
      expect(p.from).toMatch(/USA$/);
      expect(p.persona).toContain('General American English');
      expect(p.persona).toContain('HOW YOU SOUND');
      expect(p.chatPersona).toContain('HOW YOU SOUND');
    }
  });

  test('the shared SPEECH STYLE block is in each friend call prompt exactly once and never in the personas or chat', () => {
    for (const p of FRIENDS) {
      expect(p.persona).not.toContain('SPEECH STYLE');
      expect(p.chatPersona).not.toContain('SPEECH STYLE');
      const calls = [
        smallTalkInstruction('', [], p, [], null, ''),
        freeTalkInstruction('', '', null, [], p, [], null),
        missionInstruction({ id: 1, title: 'Order coffee', difficulty: 'easy', desc: 'order', target_role: 'a barista' }, '', null, [], p),
      ];
      for (const text of calls) expect(text.split(SPEECH_STYLE).length - 1).toBe(1);
      expect(buildChatInstruction(p, '', null)).not.toContain(SPEECH_STYLE);
    }
  });

  test('Ms. Park does not get the friend SPEECH STYLE block', () => {
    expect(smallTalkInstruction('', [], partnerById('park'), [], null, '')).not.toContain(SPEECH_STYLE);
  });

  test('Priya and Brian keep the facts the learner already heard in earlier calls', () => {
    const priya = partnerById('priya').persona ?? '';
    for (const word of ['Austin', 'Bengaluru', 'New Jersey', 'Kudremukh', 'cricket']) expect(priya + (partnerById('priya').storyBank ?? '')).toContain(word);
    const brian = (partnerById('brian').persona ?? '') + (partnerById('brian').storyBank ?? '');
    for (const word of ['Houston', 'Nairobi', 'Minneapolis', 'matatu', 'FAITH LIFE']) expect(brian).toContain(word);
  });
});

describe('friend coach mode across all friends', () => {
  test('call prompts with the coach switch on keep the never-correct rule and add the coach block', () => {
    for (const p of PARTNERS.filter((x) => x.id !== 'park')) {
      const coach = { correction: 'normal' as const, friendCoach: true };
      const small = smallTalkInstruction('', [], p, [], FULL_MEMORY, '', null, coach);
      const free = freeTalkInstruction('', '', null, [], p, [], FULL_MEMORY, '', null, coach);
      for (const text of [small, free]) {
        expect(text.length).toBeLessThanOrEqual(PARTNER_PROMPT_LIMIT);
        expect(text).toContain('COACH MOMENT');
        expect(text).toContain('Never correct the learner');
      }
    }
  });
});
