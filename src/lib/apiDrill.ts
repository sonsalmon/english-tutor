// 문법 미니 드릴: 서버가 문제만 보내고(정답 없음), 답은 서버가 판정한다.

export type DrillType = 'blank' | 'choice' | 'rephrase';
export type DrillQuestion = { id: string; type: DrillType; focus: string; prompt: string; options?: string[] };
export type Drill = { date: string; cached: boolean; questions: DrillQuestion[] };
export type DrillCheck = { id: string; correct: boolean; answer: string; explanation: string; loose: boolean };

// 서버가 한국어 이유(detail)를 주면 그대로 쓴다. 409는 연습할 약점이 아직 없는 경우라 다시 시도해도 소용없다.
export class DrillRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(res: Response, fallback: string): Promise<DrillRequestError> {
  let message = fallback;
  try {
    const body = await res.json();
    if (body?.detail) message = String(body.detail);
  } catch {
    // JSON이 아니면 기본 문구를 쓴다.
  }
  return new DrillRequestError(message, res.status);
}

export async function getDrill(signal?: AbortSignal): Promise<Drill> {
  const res = await fetch('/api/drill', { signal, cache: 'no-store' });
  if (!res.ok) throw await failure(res, '문제를 불러오지 못했어요.');
  const data = await res.json();
  if (!Array.isArray(data?.questions) || data.questions.length === 0) throw new DrillRequestError('문제를 불러오지 못했어요.', 502);
  return data;
}

export async function checkDrillAnswer(date: string, id: string, answer: string, signal?: AbortSignal): Promise<DrillCheck> {
  const res = await fetch('/api/drill/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date, id, answer }),
    signal,
  });
  if (!res.ok) throw await failure(res, '답을 확인하지 못했어요.');
  return res.json();
}
