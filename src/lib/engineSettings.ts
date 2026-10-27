// 친구 수다 통화에 쓸 통화 엔진 설정. coachSettings.ts와 같은 방식으로 localStorage에 둔다.
// 통화를 걸 때 읽으므로 설정을 바꾸면 다음 통화부터 적용된다. 서버 기본 경로(gemini_live, 2.5)만 서버에 필드를 보내지 않는다.

export type CallEngine = 'gemini_live' | 'gemini_live_notes' | 'gemini_live_38' | 'cascade_flux' | 'openai_live';

// v2(2026-10-27): 기본을 3.8로 바꾸며 키를 새로 했다. 예전 키에 '기본(2.5)'이 저장돼 있어도 3.8부터 시작한다.
export const CALL_ENGINE_KEY = 'english-tutor.call-engine.v2';
export const DEFAULT_CALL_ENGINE: CallEngine = 'gemini_live_38';
// 엔진 필드가 없을 때 서버가 쓰는 경로(2.5). 이 엔진을 고른 경우에만 필드를 보내지 않는다.
export const SERVER_DEFAULT_ENGINE: CallEngine = 'gemini_live';
export const CALL_ENGINES: readonly CallEngine[] = ['gemini_live', 'gemini_live_notes', 'gemini_live_38', 'cascade_flux', 'openai_live'];
// 설정 화면에 보이는 엔진은 이 목록 하나로 정한다(night-3 replica-diff 결과). 나머지는 코드에 남기고 숨긴다.
// 저장된 값이 여기 없으면 기본 엔진(3.8)으로 본다. 다시 보이려면 이름을 이 목록에 넣는다.
export const VISIBLE_CALL_ENGINES: readonly CallEngine[] = ['gemini_live_38', 'gemini_live'];

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
    return VISIBLE_CALL_ENGINES.find((e) => e === value) ?? DEFAULT_CALL_ENGINE;
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

// 요청 데이터에 더할 필드. 서버 기본 경로(2.5)이거나 친구 수다 통화가 아니면 비어 있어 서버가 기본 경로를 쓴다.
export function engineRequestField(mode: string, engine: CallEngine = loadCallEngine()): { engine?: CallEngine } {
  return engine !== SERVER_DEFAULT_ENGINE && mode === 'smalltalk' ? { engine } : {};
}
