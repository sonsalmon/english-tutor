// 교정 강도(Ms. Park)와 친구 코치 모드 설정. screenLock.ts의 화면 모드와 같은 방식으로 localStorage에 둔다.
// 통화를 걸 때 지시문을 만들면서 읽으므로 설정을 바꾸면 다음 통화부터 적용된다.

export type CorrectionStrength = 'off' | 'light' | 'normal';
export type CoachSettings = { correction: CorrectionStrength; friendCoach: boolean };

export const CORRECTION_KEY = 'english-tutor.correction-strength';
export const FRIEND_COACH_KEY = 'english-tutor.friend-coach';
export const DEFAULT_CORRECTION: CorrectionStrength = 'normal';
export const DEFAULT_FRIEND_COACH = false;
export const DEFAULT_COACH_SETTINGS: CoachSettings = { correction: DEFAULT_CORRECTION, friendCoach: DEFAULT_FRIEND_COACH };

export const CORRECTION_STRENGTHS: readonly CorrectionStrength[] = ['off', 'light', 'normal'];

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadCorrection(storage: StorageLike | null = defaultStorage()): CorrectionStrength {
  try {
    const value = storage?.getItem(CORRECTION_KEY);
    return CORRECTION_STRENGTHS.find((s) => s === value) ?? DEFAULT_CORRECTION;
  } catch {
    return DEFAULT_CORRECTION;
  }
}

export function saveCorrection(strength: CorrectionStrength, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(CORRECTION_KEY, strength);
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 세션 값만 쓴다.
  }
}

export function loadFriendCoach(storage: StorageLike | null = defaultStorage()): boolean {
  try {
    const value = storage?.getItem(FRIEND_COACH_KEY);
    return value === null || value === undefined ? DEFAULT_FRIEND_COACH : value === 'on';
  } catch {
    return DEFAULT_FRIEND_COACH;
  }
}

export function saveFriendCoach(on: boolean, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(FRIEND_COACH_KEY, on ? 'on' : 'off');
  } catch {
    // 저장소를 못 쓰는 브라우저에서는 이번 세션 값만 쓴다.
  }
}

export function loadCoachSettings(storage: StorageLike | null = defaultStorage()): CoachSettings {
  return { correction: loadCorrection(storage), friendCoach: loadFriendCoach(storage) };
}
