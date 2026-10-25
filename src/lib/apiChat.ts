import type { ChatMessage } from './api';

// 서버가 id와 pinned를 붙여 보내는 채팅 메시지.
export type ChatItem = ChatMessage & { id: string; pinned: boolean };
export type ChatView = { messages: ChatItem[]; pinned: ChatItem[] };

function isItem(m: unknown): m is ChatItem {
  const x = m as Partial<ChatItem> | null;
  return !!x && typeof x.id === 'string' && typeof x.text === 'string' && (x.role === 'me' || x.role === 'friend');
}

export function parseChatView(data: unknown): ChatView {
  const d = data as { messages?: unknown; pinned?: unknown } | null;
  return {
    messages: Array.isArray(d?.messages) ? d.messages.filter(isItem) : [],
    pinned: Array.isArray(d?.pinned) ? d.pinned.filter(isItem) : [],
  };
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // 본문이 JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export async function getChatView(id: string, signal?: AbortSignal): Promise<ChatView> {
  let res: Response;
  try {
    res = await fetch(`/api/chat/${encodeURIComponent(id)}`, { signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('대화를 불러오지 못했어요.');
  }
  if (!res.ok) throw new Error(await detail(res, '대화를 불러오지 못했어요.'));
  return parseChatView(await res.json());
}

async function post(id: string, action: 'pin' | 'delete', body: object, fallback: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`/api/chat/${encodeURIComponent(id)}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('서버에 연결하지 못했어요. 잠시 뒤에 다시 해 주세요.');
  }
  if (!res.ok) throw new Error(await detail(res, fallback));
}

export function pinChat(id: string, messageId: string, pinned: boolean): Promise<void> {
  return post(id, 'pin', { id: messageId, pinned }, pinned ? '고정하지 못했어요.' : '고정을 풀지 못했어요.');
}

export function deleteChat(id: string, messageId: string): Promise<void> {
  return post(id, 'delete', { id: messageId }, '지우지 못했어요.');
}
