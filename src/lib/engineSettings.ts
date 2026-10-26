// 친구 수다 통화에 쓸 통화 엔진 설정. coachSettings.ts와 같은 방식으로 localStorage에 둔다.
// 통화를 걸 때 읽으므로 설정을 바꾸면 다음 통화부터 적용된다. 기본값은 서버에 필드를 보내지 않는다(없으면 기본).

export type CallEngine = 'gemini_live' | 'gemini_live_notes' | 'cascade_flux' | 'openai_live';

export const CALL_ENGINE_KEY = 'english-tutor.call-engine';
export const DEFAULT_CALL_ENGINE: CallEngine = 'gemini_live';
export const CALL_ENGINES: readonly CallEngine[] = ['gemini_live', 'gemini_live_notes', 'cascade_flux', 'openai_live'];

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadCallEngine(storage: StorageLike | null = defaultStorage()): CallEngine {
  try {
    const value = storage?.getItem(CALL_ENGINE_KEY);
    return CALL_ENGINES.find((e) => e === value) ?? DEFAULT_CALL_ENGINE;
  } catch {
    return DEFAULT_CALL_ENGINE;
  }
}

export function saveCallEngine(engine: CallEngine, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(CALL_ENGINE_KEY, engine);
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 세션 값만 쓴다.
  }
}

// 요청 데이터에 더할 필드. 기본 엔진이거나 친구 수다 통화가 아니면 비어 있어 서버가 기본 경로를 쓴다.
export function engineRequestField(mode: string, engine: CallEngine = loadCallEngine()): { engine?: CallEngine } {
  return engine !== DEFAULT_CALL_ENGINE && mode === 'smalltalk' ? { engine } : {};
}
