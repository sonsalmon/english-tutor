// "나에 대한 기억" 설정(/api/memory-settings): 친구들과 Ms. Park이 알았으면 하는 내 소개글과 자동 기억 스위치.

export const ABOUT_ME_MAX = 1500;

export type MemoryRemember = { facts: boolean; threads: boolean; interests: boolean };
export type MemorySettings = { about_me: string; remember: MemoryRemember };

export const DEFAULT_MEMORY_SETTINGS: MemorySettings = {
  about_me: '',
  remember: { facts: true, threads: true, interests: true },
};

// 서버 응답을 경계에서 정리한다. 모양이 틀린 칸은 그 칸만 기본값(소개글 빈 글, 스위치 켬)으로 돌린다.
export function parseMemorySettings(data: unknown): MemorySettings {
  const raw = (typeof data === 'object' && data !== null ? data : {}) as { about_me?: unknown; remember?: unknown };
  const remember = (typeof raw.remember === 'object' && raw.remember !== null ? raw.remember : {}) as Record<string, unknown>;
  const on = (key: keyof MemoryRemember) => (typeof remember[key] === 'boolean' ? (remember[key] as boolean) : DEFAULT_MEMORY_SETTINGS.remember[key]);
  return {
    about_me: typeof raw.about_me === 'string' ? raw.about_me.trim().slice(0, ABOUT_ME_MAX) : '',
    remember: { facts: on('facts'), threads: on('threads'), interests: on('interests') },
  };
}

async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // 본문이 JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export async function getMemorySettings(signal?: AbortSignal): Promise<MemorySettings> {
  let res: Response;
  try {
    res = await fetch('/api/memory-settings', { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('기억 설정을 불러오지 못했어요.');
  }
  if (!res.ok) throw new Error(await errorDetail(res, '기억 설정을 불러오지 못했어요.'));
  return parseMemorySettings(await res.json());
}

// 통화·채팅을 걸기 전에 쓴다. 못 불러와도 통화를 막지 않고 기본값(모두 켬, 소개글 없음)으로 간다.
export async function getMemorySettingsOrDefault(signal?: AbortSignal): Promise<MemorySettings> {
  try {
    return await getMemorySettings(signal);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    return DEFAULT_MEMORY_SETTINGS;
  }
}

export async function putMemorySettings(settings: MemorySettings): Promise<MemorySettings> {
  let res: Response;
  try {
    res = await fetch('/api/memory-settings', {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ about_me: settings.about_me, remember: settings.remember }),
    });
  } catch {
    throw new Error('저장하지 못했어요. 연결을 확인해 주세요.');
  }
  if (!res.ok) throw new Error(await errorDetail(res, '저장하지 못했어요.'));
  return parseMemorySettings(await res.json());
}
