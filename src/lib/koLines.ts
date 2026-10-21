import type { ClipLine } from './api';

// 공부 화면의 한국어 줄. 번역은 줄마다 모델을 부르는 일이라 돈이 든다.
// 그래서 보는 줄만 요청하고(기본은 "탭하면 보임"), 설정에서 끄면 요청을 한 번도 보내지 않는다.

export const KO_KEY = 'et.player.ko.v1';
export type KoMode = 'hide' | 'tap' | 'show';
export type KoSettings = { enabled: boolean; mode: KoMode };
export const KO_DEFAULTS: KoSettings = { enabled: true, mode: 'tap' };

/** 항상 보임 모드에서 현재 줄 뒤로 미리 요청하는 줄 수. */
export const KO_PREFETCH = 2;
/** 번역 문맥으로 함께 보내는 앞뒤 줄 수. */
export const KO_CONTEXT = 2;
/** 서버가 한 번에 받는 줄 수의 상한. */
export const KO_MAX_LINES = 8;

const MODES: readonly KoMode[] = ['hide', 'tap', 'show'];

export const KO_MODE_LABEL: Record<KoMode, string> = { hide: '숨김', tap: '탭하면 보임', show: '항상 보임' };

export function parseKoSettings(raw: unknown): KoSettings {
  const o = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
  return {
    enabled: typeof o.enabled === 'boolean' ? o.enabled : KO_DEFAULTS.enabled,
    mode: MODES.includes(o.mode as KoMode) ? (o.mode as KoMode) : KO_DEFAULTS.mode,
  };
}

export function loadKoSettings(storage: Pick<Storage, 'getItem'> = localStorage): KoSettings {
  try {
    return parseKoSettings(JSON.parse(storage.getItem(KO_KEY) ?? 'null'));
  } catch {
    return KO_DEFAULTS;
  }
}

export function saveKoSettings(settings: KoSettings, storage: Pick<Storage, 'setItem'> = localStorage): void {
  try {
    storage.setItem(KO_KEY, JSON.stringify(settings));
  } catch {
    /* storage unavailable: 이번 화면에서만 유지된다 */
  }
}

export function nextKoMode(mode: KoMode): KoMode {
  return MODES[(MODES.indexOf(mode) + 1) % MODES.length];
}

export type KoPlan = { lines: { id: number; text: string }[]; before: string[]; after: string[] };

export type KoPlanInput = {
  lines: readonly ClipLine[];
  index: number;
  settings: KoSettings;
  /** 탭하면 보임 모드에서 사용자가 지금 줄을 탭했는지. */
  revealed: boolean;
  /** 이미 받았거나 요청 중이거나 실패해서 다시 요청하면 안 되는 줄. */
  skip: (id: number) => boolean;
};

// 지금 보내야 할 번역 요청. 보낼 것이 없으면 null.
// 탭하면 보임: 탭한 지금 줄 하나. 항상 보임: 지금 줄과 뒤 두 줄(체감 지연을 줄이려고 미리 요청).
export function planKoRequest({ lines, index, settings, revealed, skip }: KoPlanInput): KoPlan | null {
  if (!settings.enabled || settings.mode === 'hide' || index < 0 || index >= lines.length) return null;
  const wanted = settings.mode === 'show' ? Array.from({ length: KO_PREFETCH + 1 }, (_, i) => index + i) : revealed ? [index] : [];
  const picked = wanted.filter((i) => i < lines.length && !skip(lines[i].id)).slice(0, KO_MAX_LINES);
  if (!picked.length) return null;
  const first = picked[0];
  const last = picked[picked.length - 1];
  return {
    lines: picked.map((i) => ({ id: lines[i].id, text: lines[i].text })),
    before: lines.slice(Math.max(0, first - KO_CONTEXT), first).map((l) => l.text),
    after: lines.slice(last + 1, last + 1 + KO_CONTEXT).map((l) => l.text),
  };
}

export type KoFail = 'error' | 'capped' | 'unavailable';
export type KoView = 'off' | 'hidden' | 'loading' | 'text' | KoFail;

// 지금 줄의 한국어 칸이 보여 줄 것.
export function koView(input: { settings: KoSettings; hasLine: boolean; revealed: boolean; ko: string | null; fail: KoFail | null }): KoView {
  const { settings, hasLine, revealed, ko, fail } = input;
  if (!settings.enabled || settings.mode === 'hide' || !hasLine) return 'off';
  if (settings.mode === 'tap' && !revealed) return 'hidden';
  if (ko !== null) return 'text';
  return fail ?? 'loading';
}
