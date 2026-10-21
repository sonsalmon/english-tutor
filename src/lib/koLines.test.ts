import { describe, expect, test } from 'bun:test';
import type { ClipLine } from './api';
import { KO_DEFAULTS, KO_KEY, koView, loadKoSettings, nextKoMode, parseKoSettings, planKoRequest, saveKoSettings, type KoSettings } from './koLines';

const lines: ClipLine[] = Array.from({ length: 6 }, (_, i) => ({ id: (i + 1) * 1000, start: i * 2, end: i * 2 + 2, text: `line ${i}` }));
const never = () => false;
const tap: KoSettings = { enabled: true, mode: 'tap' };
const show: KoSettings = { enabled: true, mode: 'show' };

function memory(initial: string | null = null) {
  const store = new Map<string, string>();
  if (initial !== null) store.set(KO_KEY, initial);
  return { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
}

describe('한국어 설정 저장', () => {
  test('처음 값은 켬 + 탭하면 보임', () => {
    expect(loadKoSettings(memory())).toEqual({ enabled: true, mode: 'tap' });
    expect(KO_DEFAULTS).toEqual({ enabled: true, mode: 'tap' });
  });

  test('저장한 값을 그대로 읽는다(새로고침 뒤에도 유지)', () => {
    const storage = memory();
    saveKoSettings({ enabled: false, mode: 'show' }, storage);
    expect(loadKoSettings(storage)).toEqual({ enabled: false, mode: 'show' });
  });

  test('깨진 값은 칸마다 처음 값으로 되돌린다', () => {
    expect(loadKoSettings(memory('{nope'))).toEqual(KO_DEFAULTS);
    expect(parseKoSettings({ enabled: 'yes', mode: 'x' })).toEqual(KO_DEFAULTS);
    expect(parseKoSettings({ enabled: false })).toEqual({ enabled: false, mode: 'tap' });
    expect(parseKoSettings(null)).toEqual(KO_DEFAULTS);
  });

  test('저장소가 막혀 있어도 던지지 않는다', () => {
    expect(() => saveKoSettings(KO_DEFAULTS, { setItem: () => { throw new Error('quota'); } })).not.toThrow();
    expect(loadKoSettings({ getItem: () => { throw new Error('blocked'); } })).toEqual(KO_DEFAULTS);
  });

  test('K 순환: 숨김 -> 탭하면 보임 -> 항상 보임 -> 숨김', () => {
    expect(nextKoMode('hide')).toBe('tap');
    expect(nextKoMode('tap')).toBe('show');
    expect(nextKoMode('show')).toBe('hide');
  });
});

describe('planKoRequest: 어떤 줄을 요청하는가', () => {
  test('설정에서 끄면 어떤 모드에서도 요청이 없다(0 호출)', () => {
    for (const mode of ['hide', 'tap', 'show'] as const)
      expect(planKoRequest({ lines, index: 2, settings: { enabled: false, mode }, revealed: true, skip: never })).toBeNull();
  });

  test('숨김 모드와 줄이 없는 상태는 요청이 없다', () => {
    expect(planKoRequest({ lines, index: 2, settings: { enabled: true, mode: 'hide' }, revealed: true, skip: never })).toBeNull();
    expect(planKoRequest({ lines, index: -1, settings: show, revealed: false, skip: never })).toBeNull();
    expect(planKoRequest({ lines: [], index: 0, settings: show, revealed: false, skip: never })).toBeNull();
  });

  test('탭하면 보임: 탭하기 전에는 요청이 없고, 탭하면 그 줄 하나만 앞뒤 두 줄 문맥과 함께 요청한다', () => {
    expect(planKoRequest({ lines, index: 2, settings: tap, revealed: false, skip: never })).toBeNull();
    expect(planKoRequest({ lines, index: 2, settings: tap, revealed: true, skip: never })).toEqual({
      lines: [{ id: 3000, text: 'line 2' }],
      before: ['line 0', 'line 1'],
      after: ['line 3', 'line 4'],
    });
  });

  test('항상 보임: 지금 줄과 뒤 두 줄을 한 번에 요청한다', () => {
    expect(planKoRequest({ lines, index: 1, settings: show, revealed: false, skip: never })).toEqual({
      lines: [
        { id: 2000, text: 'line 1' },
        { id: 3000, text: 'line 2' },
        { id: 4000, text: 'line 3' },
      ],
      before: ['line 0'],
      after: ['line 4', 'line 5'],
    });
  });

  test('이미 받았거나 요청 중이거나 실패한 줄은 다시 요청하지 않는다', () => {
    const plan = planKoRequest({ lines, index: 1, settings: show, revealed: false, skip: (id) => id === 2000 || id === 4000 });
    expect(plan?.lines).toEqual([{ id: 3000, text: 'line 2' }]);
    expect(planKoRequest({ lines, index: 1, settings: show, revealed: false, skip: () => true })).toBeNull();
    expect(planKoRequest({ lines, index: 2, settings: tap, revealed: true, skip: (id) => id === 3000 })).toBeNull();
  });

  test('마지막 줄 근처에서는 있는 줄까지만 요청하고 문맥이 비어도 된다', () => {
    expect(planKoRequest({ lines, index: 5, settings: show, revealed: false, skip: never })).toEqual({
      lines: [{ id: 6000, text: 'line 5' }],
      before: ['line 3', 'line 4'],
      after: [],
    });
  });
});

describe('koView: 한국어 칸이 보여 줄 것', () => {
  const base = { settings: tap, hasLine: true, revealed: false, ko: null, fail: null };

  test('꺼짐, 숨김, 줄 없음은 칸이 없다', () => {
    expect(koView({ ...base, settings: { enabled: false, mode: 'show' } })).toBe('off');
    expect(koView({ ...base, settings: { enabled: true, mode: 'hide' } })).toBe('off');
    expect(koView({ ...base, hasLine: false })).toBe('off');
  });

  test('탭하면 보임: 탭하기 전엔 번역이 있어도 가려져 있다', () => {
    expect(koView({ ...base, ko: '안녕' })).toBe('hidden');
    expect(koView({ ...base, revealed: true, ko: '안녕' })).toBe('text');
  });

  test('받는 중, 실패, 한도, 서버 꺼짐', () => {
    expect(koView({ ...base, revealed: true })).toBe('loading');
    expect(koView({ ...base, revealed: true, fail: 'error' })).toBe('error');
    expect(koView({ ...base, revealed: true, fail: 'capped' })).toBe('capped');
    expect(koView({ ...base, revealed: true, fail: 'unavailable' })).toBe('unavailable');
  });

  test('항상 보임: 탭 없이 바로 번역이 보인다', () => {
    expect(koView({ ...base, settings: show, ko: '안녕' })).toBe('text');
    expect(koView({ ...base, settings: show })).toBe('loading');
  });
});
