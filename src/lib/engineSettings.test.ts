import { describe, expect, test } from 'bun:test';
import { CALL_ENGINE_KEY, CALL_ENGINES, DEFAULT_CALL_ENGINE, engineRequestField, loadCallEngine, saveCallEngine, SERVER_DEFAULT_ENGINE, VISIBLE_CALL_ENGINES } from './engineSettings';

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

describe('call engine storage', () => {
  test('defaults to gemini_live_38 when nothing is saved', () => {
    expect(DEFAULT_CALL_ENGINE).toBe('gemini_live_38');
    expect(loadCallEngine(memory())).toBe('gemini_live_38');
    expect(loadCallEngine(null)).toBe('gemini_live_38');
  });

  test('a value saved under the old key is ignored, so the new default applies', () => {
    expect(loadCallEngine(memory({ 'english-tutor.call-engine': 'gemini_live' }))).toBe('gemini_live_38');
  });

  test('the picker shows Gemini 3.8 Live first, then 2.5', () => {
    expect(VISIBLE_CALL_ENGINES).toEqual(['gemini_live_38', 'gemini_live']);
    for (const engine of VISIBLE_CALL_ENGINES) expect(CALL_ENGINES).toContain(engine);
  });

  test('saves and loads each visible engine', () => {
    for (const engine of VISIBLE_CALL_ENGINES) {
      const store = memory();
      saveCallEngine(engine, store);
      expect(store.data[CALL_ENGINE_KEY]).toBe(engine);
      expect(loadCallEngine(store)).toBe(engine);
    }
  });

  test('a hidden saved engine is treated as the default (3.8) and sent as 3.8', () => {
    for (const engine of ['gemini_live_notes', 'cascade_flux', 'openai_live'] as const) {
      expect(VISIBLE_CALL_ENGINES).not.toContain(engine);
      const loaded = loadCallEngine(memory({ [CALL_ENGINE_KEY]: engine }));
      expect(loaded).toBe(DEFAULT_CALL_ENGINE);
      expect(engineRequestField('smalltalk', loaded)).toEqual({ engine: 'gemini_live_38' });
    }
  });

  test('an unknown saved value falls back to the default', () => {
    expect(loadCallEngine(memory({ [CALL_ENGINE_KEY]: 'whisper_x' }))).toBe('gemini_live_38');
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
    expect(loadCallEngine(broken)).toBe('gemini_live_38');
    expect(() => saveCallEngine('gemini_live', broken)).not.toThrow();
  });
});

describe('engineRequestField', () => {
  test('sends nothing for the server default engine (2.5)', () => {
    expect(SERVER_DEFAULT_ENGINE).toBe('gemini_live');
    expect(engineRequestField('smalltalk', 'gemini_live')).toEqual({});
  });

  test('sends the app default (3.8) for smalltalk calls', () => {
    expect(engineRequestField('smalltalk', DEFAULT_CALL_ENGINE)).toEqual({ engine: 'gemini_live_38' });
  });

  test('sends the engine only for smalltalk calls', () => {
    expect(engineRequestField('smalltalk', 'gemini_live_38')).toEqual({ engine: 'gemini_live_38' });
    for (const mode of ['mission', 'freetalk', 'teachback', 'lesson']) {
      expect(engineRequestField(mode, 'gemini_live_38')).toEqual({});
    }
  });
});
