export const NETWORK_MESSAGE = '서버에 연결하지 못했어요. 폰의 Tailscale이 켜져 있는지 확인하고 다시 시도해 주세요.';
export const MIC_MESSAGE = '마이크를 쓸 수 없어요. iPhone 설정에서 이 앱의 마이크를 허용한 뒤 다시 시도해 주세요.';
const FALLBACK_MESSAGE = '문제가 생겼어요. 잠시 뒤에 다시 시도해 주세요.';

const NETWORK_TEXT = /failed to fetch|load failed|networkerror|network request failed|fetch failed/i;
const HANGUL = /[가-힣]/;

function nameOf(e: unknown): string {
  return typeof e === 'object' && e !== null && 'name' in e ? String((e as { name: unknown }).name) : '';
}

function messageOf(e: unknown): string {
  if (typeof e === 'string') return e;
  return typeof e === 'object' && e !== null && 'message' in e ? String((e as { message: unknown }).message) : '';
}

// 화면에 보여 줄 오류 문구. 영어 원문(TypeError: Failed to fetch 등)은 절대 그대로 내보내지 않는다.
// 서버가 보낸 한국어 메시지는 그대로 살리고, 그 밖에는 fallback(없으면 기본 문구)을 쓴다.
export function friendlyError(e: unknown, fallback: string = FALLBACK_MESSAGE): string {
  const name = nameOf(e);
  const message = messageOf(e);
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return MIC_MESSAGE;
  if (name === 'TypeError' || name === 'NetworkError' || NETWORK_TEXT.test(message)) return NETWORK_MESSAGE;
  if (HANGUL.test(message)) return message;
  return fallback;
}
