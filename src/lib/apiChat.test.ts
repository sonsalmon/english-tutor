import { describe, expect, test } from 'bun:test';
import { parseChatView } from './apiChat';

describe('parseChatView', () => {
  test('keeps items with id and drops the rest', () => {
    const ok = { id: 'a', role: 'me', text: 'hi', at: 't', pinned: true };
    const v = parseChatView({ messages: [ok, { role: 'me', text: 'no id' }, null], pinned: [ok] });
    expect(v.messages).toEqual([ok]);
    expect(v.pinned).toEqual([ok]);
  });
  test('survives garbage', () => {
    expect(parseChatView(null)).toEqual({ messages: [], pinned: [] });
    expect(parseChatView({ messages: 5 })).toEqual({ messages: [], pinned: [] });
  });
});
