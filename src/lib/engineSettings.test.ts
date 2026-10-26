import { describe, expect, test } from 'bun:test';
import { CALL_ENGINE_KEY, DEFAULT_CALL_ENGINE, engineRequestField, loadCallEngine, saveCallEngine } from './engineSettings';

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

describe('call engine storage', () => {
  test('defaults to gemini_live when nothing is saved', () => {
    expect(DEFAULT_CALL_ENGINE).toBe('gemini_live');
    expect(loadCallEngine(memory())).toBe('gemini_live');
    expect(loadCallEngine(null)).toBe('gemini_live');
  });

  test('saves and loads each engine', () => {
    for (const engine of ['gemini_live', 'gemini_live_notes', 'cascade_flux', 'openai_live'] as const) {
      const store = memory();
      saveCallEngine(engine, store);
      expect(store.data[CALL_ENGINE_KEY]).toBe(engine);
      expect(loadCallEngine(store)).toBe(engine);
    }
  });

  test('an unknown saved value falls back to the default', () => {
    expect(loadCallEngine(memory({ [CALL_ENGINE_KEY]: 'whisper_x' }))).toBe('gemini_live');
  });

  test('a broken storage falls back to the default instead of throwing', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    expect(loadCallEngine(broken)).toBe('gemini_live');
    expect(() => saveCallEngine('cascade_flux', broken)).not.toThrow();
  });
});

describe('engineRequestField', () => {
  test('sends nothing for the default engine', () => {
    expect(engineRequestField('smalltalk', 'gemini_live')).toEqual({});
  });

  test('sends the engine only for smalltalk calls', () => {
    expect(engineRequestField('smalltalk', 'cascade_flux')).toEqual({ engine: 'cascade_flux' });
    expect(engineRequestField('smalltalk', 'gemini_live_notes')).toEqual({ engine: 'gemini_live_notes' });
    for (const mode of ['mission', 'freetalk', 'teachback', 'lesson']) {
      expect(engineRequestField(mode, 'cascade_flux')).toEqual({});
    }
  });
});
