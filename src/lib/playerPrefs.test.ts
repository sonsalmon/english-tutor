import { describe, expect, test } from 'bun:test';
import { loadPrefs, nextEngMode, nextRepeat, nextTextSize, parsePrefs, PREFS_KEY, RATES, savePrefs, STUDY_DEFAULTS, stepRate, visibleRates } from './playerPrefs';

function memory(initial: string | null = null) {
  const store = new Map<string, string>();
  if (initial !== null) store.set(PREFS_KEY, initial);
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  };
}

describe('prefs 저장과 읽기', () => {
  test('저장한 값을 그대로 읽는다(새로고침 뒤에도 유지)', () => {
    const storage = memory();
    const prefs = { rate: 0.75, repeat: 'x3', autoPause: false, engMode: 'blur', textSize: 'lg' } as const;
    savePrefs(prefs, storage);
    expect(loadPrefs(storage)).toEqual(prefs);
  });

  test('저장된 값이 없으면 공부 화면 처음 값: 줄마다 멈춤 켬, 속도 1, 반복 끔, 영어 보임', () => {
    expect(loadPrefs(memory())).toEqual({ rate: 1, repeat: 'off', autoPause: true, engMode: 'show', textSize: 'md' });
    expect(STUDY_DEFAULTS.autoPause).toBe(true);
  });

  test('깨진 JSON이나 엉뚱한 값은 칸마다 처음 값으로 되돌린다', () => {
    expect(loadPrefs(memory('{not json'))).toEqual(STUDY_DEFAULTS);
    expect(parsePrefs({ rate: 3, repeat: 'x9', autoPause: 'yes', engMode: 'x', textSize: 'huge' })).toEqual(STUDY_DEFAULTS);
    expect(parsePrefs({ rate: 1.25, autoPause: false })).toEqual({ ...STUDY_DEFAULTS, rate: 1.25, autoPause: false });
    expect(parsePrefs(null)).toEqual(STUDY_DEFAULTS);
    expect(parsePrefs([1, 2])).toEqual(STUDY_DEFAULTS);
  });

  test('저장소가 막혀 있어도 던지지 않는다', () => {
    expect(() => savePrefs(STUDY_DEFAULTS, { setItem: () => { throw new Error('quota'); } })).not.toThrow();
    expect(loadPrefs({ getItem: () => { throw new Error('blocked'); } })).toEqual(STUDY_DEFAULTS);
  });
});

describe('순환과 속도 칸', () => {
  test('반복은 끔, 3번, 무한 순으로 돌고 영어 자막은 보임, 흐림, 숨김 순으로 돈다', () => {
    expect(nextRepeat('off')).toBe('x3');
    expect(nextRepeat('x3')).toBe('inf');
    expect(nextRepeat('inf')).toBe('off');
    expect(nextEngMode('show')).toBe('blur');
    expect(nextEngMode('blur')).toBe('hide');
    expect(nextEngMode('hide')).toBe('show');
    expect(nextTextSize('sm')).toBe('md');
    expect(nextTextSize('md')).toBe('lg');
    expect(nextTextSize('lg')).toBe('sm');
  });

  test('visibleRates: 영상이 받는 속도와 겹치는 것만, 목록이 비었거나 겹치지 않으면 전부', () => {
    expect(visibleRates([0.25, 0.5, 1, 2])).toEqual([0.5, 1]);
    expect(visibleRates([])).toEqual([...RATES]);
    expect(visibleRates([2])).toEqual([...RATES]);
  });

  test('stepRate: 한 칸씩 움직이고 끝에서 멈추며, 목록에 없는 속도는 가장 가까운 칸에서 시작한다', () => {
    expect(stepRate(RATES, 1, -1)).toBe(0.75);
    expect(stepRate(RATES, 1, 1)).toBe(1.25);
    expect(stepRate(RATES, 0.5, -1)).toBe(0.5);
    expect(stepRate(RATES, 1.5, 1)).toBe(1.5);
    expect(stepRate([0.5, 1], 0.75, 1)).toBe(1);
    expect(stepRate([0.5, 1], 1.5, 1)).toBe(1);
  });
});
