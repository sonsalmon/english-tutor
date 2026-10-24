import { describe, expect, test } from 'bun:test';
import { KEYBOARD_MIN_PX, keyboardInset } from './keyboardInset';

describe('keyboardInset', () => {
  test('keyboard open: the covered bottom height', () => {
    expect(keyboardInset(844, 508, 0)).toBe(336);
  });

  test('page scrolled up by iOS while the keyboard is open still counts only what is covered', () => {
    expect(keyboardInset(844, 508, 120)).toBe(216);
  });

  test('small differences (address bar, rounding) are not a keyboard', () => {
    expect(keyboardInset(844, 844 - (KEYBOARD_MIN_PX - 1), 0)).toBe(0);
    expect(keyboardInset(844, 844, 0)).toBe(0);
    expect(keyboardInset(844, 900, 0)).toBe(0);
  });
});
