import { describe, expect, test } from 'bun:test';
import { keyCommand, SHORTCUTS, type KeyCommand } from './studyKeys';

const plain = (key: string) => ({ key, ctrlKey: false, metaKey: false, altKey: false });

describe('단축키 표', () => {
  test('Space, A/D/S, 방향키, R, Q, [, ], C, 쉼표, 마침표, ?, Esc가 명세 표대로 대응한다', () => {
    const table: [string, KeyCommand][] = [
      [' ', 'toggle'],
      ['a', 'prev'],
      ['A', 'prev'],
      ['ArrowLeft', 'prev'],
      ['d', 'next'],
      ['D', 'next'],
      ['ArrowRight', 'next'],
      ['s', 'replay'],
      ['S', 'replay'],
      ['ArrowDown', 'replay'],
      ['r', 'repeat'],
      ['R', 'repeat'],
      ['q', 'autoPause'],
      ['Q', 'autoPause'],
      ['[', 'slower'],
      [']', 'faster'],
      ['c', 'eng'],
      ['C', 'eng'],
      [',', 'syncEarlier'],
      ['.', 'syncLater'],
      ['?', 'help'],
      ['Escape', 'close'],
    ];
    for (const [key, command] of table) expect(keyCommand(plain(key), false)).toBe(command);
  });

  test('입력칸에 포커스가 있으면 아무것도 하지 않는다', () => {
    for (const key of [' ', 'a', 'R', 'Escape', 'ArrowLeft']) expect(keyCommand(plain(key), true)).toBeNull();
  });

  test('Ctrl, Meta, Alt가 눌려 있으면 브라우저 단축키에 양보한다', () => {
    for (const mod of ['ctrlKey', 'metaKey', 'altKey'] as const) expect(keyCommand({ ...plain('r'), [mod]: true }, false)).toBeNull();
  });

  test('표에 없는 키는 무시한다', () => {
    for (const key of ['x', 'Enter', 'Tab', '1', 'ArrowUp']) expect(keyCommand(plain(key), false)).toBeNull();
  });

  test('도움말 목록이 단축키마다 한 줄씩 있다', () => {
    expect(SHORTCUTS.length).toBe(11);
    expect(new Set(SHORTCUTS.map((s) => s.keys)).size).toBe(SHORTCUTS.length);
  });
});
