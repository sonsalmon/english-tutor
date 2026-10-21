import { DEFAULT_SETTINGS, type PlayerSettings, type RepeatMode } from './playerMachine';

export const PREFS_KEY = 'et.player.prefs.v1';
export const RATES = [0.5, 0.75, 1, 1.25, 1.5] as const;

export type EngMode = 'show' | 'blur' | 'hide';
export type TextSize = 'sm' | 'md' | 'lg';
export type Prefs = PlayerSettings & { engMode: EngMode; textSize: TextSize };

// 공부 화면의 처음 값: 줄마다 멈춤이 켜져 있다(요약·피드의 재생기는 이 값을 읽지 않고 이어서 재생한다).
export const STUDY_DEFAULTS: Prefs = { ...DEFAULT_SETTINGS, autoPause: true, engMode: 'show', textSize: 'md' };

const REPEATS: readonly RepeatMode[] = ['off', 'x3', 'inf'];
const ENG_MODES: readonly EngMode[] = ['show', 'blur', 'hide'];
const TEXT_SIZES: readonly TextSize[] = ['sm', 'md', 'lg'];

// 저장된 값에서 쓸 수 있는 칸만 살리고 나머지는 처음 값으로 둔다(옛 버전이나 손댄 값에도 화면이 멈추지 않게).
export function parsePrefs(raw: unknown): Prefs {
  const o = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
  return {
    rate: (RATES as readonly unknown[]).includes(o.rate) ? (o.rate as number) : STUDY_DEFAULTS.rate,
    repeat: REPEATS.includes(o.repeat as RepeatMode) ? (o.repeat as RepeatMode) : STUDY_DEFAULTS.repeat,
    autoPause: typeof o.autoPause === 'boolean' ? o.autoPause : STUDY_DEFAULTS.autoPause,
    engMode: ENG_MODES.includes(o.engMode as EngMode) ? (o.engMode as EngMode) : STUDY_DEFAULTS.engMode,
    textSize: TEXT_SIZES.includes(o.textSize as TextSize) ? (o.textSize as TextSize) : STUDY_DEFAULTS.textSize,
  };
}

export function loadPrefs(storage: Pick<Storage, 'getItem'> = localStorage): Prefs {
  try {
    return parsePrefs(JSON.parse(storage.getItem(PREFS_KEY) ?? 'null'));
  } catch {
    return STUDY_DEFAULTS;
  }
}

export function savePrefs(prefs: Prefs, storage: Pick<Storage, 'setItem'> = localStorage): void {
  try {
    storage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* storage unavailable: 이번 화면에서만 유지된다 */
  }
}

export function nextRepeat(mode: RepeatMode): RepeatMode {
  return REPEATS[(REPEATS.indexOf(mode) + 1) % REPEATS.length];
}

export function nextEngMode(mode: EngMode): EngMode {
  return ENG_MODES[(ENG_MODES.indexOf(mode) + 1) % ENG_MODES.length];
}

export function nextTextSize(size: TextSize): TextSize {
  return TEXT_SIZES[(TEXT_SIZES.indexOf(size) + 1) % TEXT_SIZES.length];
}

// 영상이 실제로 받는 속도만 칩으로 보인다. 목록을 못 받았거나 겹치는 값이 없으면 전부 보인다.
export function visibleRates(available: readonly number[]): number[] {
  const both = RATES.filter((r) => available.includes(r));
  return both.length ? both : [...RATES];
}

// 요약·피드의 속도 칩용: 보이는 속도를 느린 쪽에서 빠른 쪽으로 돌고, 끝에서 처음으로 돌아간다.
export function cycleRate(rates: readonly number[], rate: number): number {
  const up = stepRate(rates, rate, 1);
  return up > rate ? up : rates[0];
}

// 보이는 속도 목록에서 한 칸 느리게(-1) 또는 빠르게(+1). 끝에서는 멈춘다. 목록에 없는 속도면 가장 가까운 칸에서 시작한다.
export function stepRate(rates: readonly number[], rate: number, direction: -1 | 1): number {
  let nearest = 0;
  rates.forEach((r, i) => {
    if (Math.abs(r - rate) < Math.abs(rates[nearest] - rate)) nearest = i;
  });
  return rates[Math.min(rates.length - 1, Math.max(0, nearest + direction))];
}
