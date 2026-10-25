import { ChevronLeft, MoreHorizontal, Phone, Pin, PinOff, SendHorizontal, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Avatar } from '../components/Avatar';
import { WordText } from '../components/WordText';
import { QuietButton } from '../components/ui';
import { closeChat, getPartnerMemory, sendChat, type PartnerMemory, type Wordbook } from '../lib/api';
import { deleteChat, getChatView, pinChat, type ChatItem } from '../lib/apiChat';
import { clock, sameDay, yesterdayOf } from '../lib/callFormat';
import { friendlyError } from '../lib/errors';
import { buildChatInstruction } from '../lib/instructions';
import { partnerMeta, type Partner } from '../lib/partners';
import { go } from '../lib/router';
import { useSwipe } from '../lib/swipe';
import { visibleFriends } from '../lib/visibility';

const IDLE_CLOSE_MS = 2 * 60 * 1000;
const MAX_LENGTH = 1000;
const GAP_MS = 5 * 60 * 1000;
const LONG_PRESS_MS = 450;
const MOVE_CANCEL_PX = 8;

function dayLabel(d: Date, now = new Date()): string {
  if (sameDay(d, now)) return '오늘';
  if (sameDay(d, yesterdayOf(now))) return '어제';
  return d.toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' });
}

type ConversationProps = {
  partner: Partner;
  brief: string;
  interests?: string[];
  wordbook?: Wordbook | null;
  profileReady: boolean;
  onCall: (partnerId: string) => void;
};

function Conversation({ partner, brief, interests, wordbook, profileReady, onCall }: ConversationProps) {
  const id = partner.id;
  const [messages, setMessages] = useState<ChatItem[] | null>(null);
  const [pinned, setPinned] = useState<ChatItem[]>([]);
  const [menu, setMenu] = useState<ChatItem | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [menuBusy, setMenuBusy] = useState(false);
  const [menuError, setMenuError] = useState<string | null>(null);
  const press = useRef<{ timer: number; x: number; y: number } | null>(null);
  const pressed = useRef(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const alive = useRef(true);
  const dirty = useRef(false);
  const idleTimer = useRef<number | undefined>(undefined);
  const swipe = useSwipe({ onLeft: () => go('person', false, id) });
  const memory = useRef<PartnerMemory | null>(null);
  const memoryLoad = useRef<Promise<void>>(Promise.resolve());
  const memoryStale = useRef(false);

  const loadMemory = useCallback(() => {
    memoryLoad.current = getPartnerMemory(id).then(
      (m) => {
        memory.current = m;
      },
      () => {},
    );
  }, [id]);

  useEffect(() => {
    setMessages(null);
    setLoadError(null);
    const controller = new AbortController();
    getChatView(id, controller.signal).then(
      (v) => {
        setMessages(v.messages);
        setPinned(v.pinned);
      },
      (e) => {
        if (!controller.signal.aborted) setLoadError(friendlyError(e, '대화를 불러오지 못했어요.'));
      },
    );
    return () => controller.abort();
  }, [id, reload]);

  useEffect(() => {
    loadMemory();
  }, [loadMemory]);

  // 대화를 떠날 때(화면 이동, 탭 숨김, 2분 동안 조용함) 새로 오간 메시지가 있으면 서버에 한 번 알린다.
  const flush = useCallback(() => {
    window.clearTimeout(idleTimer.current);
    if (!dirty.current) return;
    dirty.current = false;
    memoryStale.current = true;
    closeChat(id);
  }, [id]);

  const armIdle = useCallback(() => {
    window.clearTimeout(idleTimer.current);
    if (dirty.current) idleTimer.current = window.setTimeout(flush, IDLE_CLOSE_MS);
  }, [flush]);

  useEffect(() => {
    alive.current = true;
    const onHide = () => {
      if (document.visibilityState === 'hidden') flush();
    };
    document.addEventListener('visibilitychange', onHide);
    window.addEventListener('pagehide', flush);
    return () => {
      alive.current = false;
      document.removeEventListener('visibilitychange', onHide);
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [flush]);

  const count = messages?.length ?? 0;
  useLayoutEffect(() => {
    window.scrollTo({ top: document.documentElement.scrollHeight });
  }, [count, pending]);

  useLayoutEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight + el.offsetHeight - el.clientHeight, 160)}px`;
  }, [draft]);

  const ready = messages !== null && profileReady;
  const sending = pending !== null;

  async function submit() {
    const text = draft.trim();
    if (!text || sending || !ready) return;
    setError(null);
    setPending(text);
    setDraft('');
    try {
      if (memoryStale.current) {
        memoryStale.current = false;
        loadMemory();
      }
      await memoryLoad.current;
      const instruction = buildChatInstruction(partner, brief, memory.current, interests ?? [], wordbook ?? null);
      const res = await sendChat(id, instruction, text);
      setMessages((prev) => [...(prev ?? []), ...(res.messages as ChatItem[])]);
      if (alive.current) {
        dirty.current = true;
        armIdle();
      } else {
        closeChat(id);
      }
    } catch (e) {
      setDraft(text);
      setError(friendlyError(e, '메시지를 보내지 못했어요. 잠시 뒤에 다시 보내 주세요.'));
    } finally {
      setPending(null);
      textarea.current?.focus({ preventScroll: true });
    }
  }

  function openMenu(m: ChatItem) {
    setMenu(m);
    setConfirmDelete(false);
    setMenuError(null);
  }

  function cancelPress() {
    if (press.current) window.clearTimeout(press.current.timer);
    press.current = null;
  }

  function pressHandlers(m: ChatItem) {
    return {
      onPointerDown: (e: React.PointerEvent) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        cancelPress();
        pressed.current = false;
        const timer = window.setTimeout(() => {
          pressed.current = true;
          press.current = null;
          navigator.vibrate?.(10);
          openMenu(m);
        }, LONG_PRESS_MS);
        press.current = { timer, x: e.clientX, y: e.clientY };
      },
      onPointerMove: (e: React.PointerEvent) => {
        const p = press.current;
        if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > MOVE_CANCEL_PX) cancelPress();
      },
      onPointerUp: cancelPress,
      onPointerCancel: cancelPress,
      onPointerLeave: cancelPress,
      onContextMenu: (e: React.MouseEvent) => e.preventDefault(),
      // 길게 눌러 메뉴를 연 손가락이 떼어질 때 단어 탭으로 번지지 않게 한다.
      onClickCapture: (e: React.MouseEvent) => {
        if (pressed.current) {
          pressed.current = false;
          e.stopPropagation();
          e.preventDefault();
        }
      },
    };
  }

  async function togglePin(m: ChatItem) {
    setMenuBusy(true);
    setMenuError(null);
    try {
      const next = !m.pinned;
      await pinChat(id, m.id, next);
      const updated = { ...m, pinned: next };
      setMessages((prev) => (prev ?? []).map((x) => (x.id === m.id ? updated : x)));
      setPinned((prev) => (next ? [...prev.filter((x) => x.id !== m.id), updated] : prev.filter((x) => x.id !== m.id)));
      setMenu(null);
    } catch (e) {
      setMenuError(friendlyError(e, m.pinned ? '고정을 풀지 못했어요.' : '고정하지 못했어요.'));
    } finally {
      setMenuBusy(false);
    }
  }

  async function removeMessage(m: ChatItem) {
    setMenuBusy(true);
    setMenuError(null);
    try {
      await deleteChat(id, m.id);
      setMessages((prev) => (prev ?? []).filter((x) => x.id !== m.id));
      setPinned((prev) => prev.filter((x) => x.id !== m.id));
      setMenu(null);
    } catch (e) {
      setMenuError(friendlyError(e, '지우지 못했어요.'));
    } finally {
      setMenuBusy(false);
    }
  }

  function jumpTo(m: ChatItem) {
    const el = document.getElementById(`msg-${m.id}`);
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } else {
      openMenu(m);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    void submit();
  }

  const list = messages ?? [];
  const now = new Date();

  return (
    <main
      {...swipe.handlers}
      style={swipe.style}
      className="mx-auto flex min-h-dvh w-full max-w-[480px] flex-col px-5 lg:max-w-[760px] lg:px-10 lg:min-h-dvh!"
    >
      <header className="sticky top-0 z-10 -mx-5 flex items-center gap-2 border-b border-line bg-paper/95 px-3 pt-[calc(8px+env(safe-area-inset-top))] pb-2 backdrop-blur lg:mx-0 lg:px-0 lg:pt-8 lg:pb-3">
        <button
          type="button"
          onClick={() => go('person', false, id)}
          aria-label="뒤로"
          className="grid size-11 shrink-0 place-items-center rounded-full text-ink hover:bg-line/60"
        >
          <ChevronLeft size={24} aria-hidden />
        </button>
        <Avatar partner={partner} size={40} />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-lg leading-tight font-bold">{partner.name}</h1>
          <p className="truncate text-xs text-ink-soft">{partnerMeta(partner)}</p>
        </div>
        <button
          type="button"
          onClick={() => onCall(partner.id)}
          className="flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-4 font-semibold text-ink hover:bg-paper"
        >
          <Phone size={18} aria-hidden />
          전화하기
        </button>
      </header>

      {pinned.length > 0 && (
        <section aria-label="고정한 메시지" className="sticky top-[calc(61px+env(safe-area-inset-top))] z-[9] -mx-5 max-h-36 overflow-y-auto border-b border-line bg-surface/95 px-5 py-1.5 backdrop-blur lg:mx-0 lg:px-0">
          <ul>
            {pinned.map((m) => (
              <li key={m.id} className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => jumpTo(m)}
                  className="flex min-h-11 min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <Pin size={14} aria-hidden className="shrink-0 text-ink-soft" />
                  <span lang={m.role === 'me' ? undefined : 'en'} className="truncate text-sm text-ink">
                    {m.text}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => openMenu(m)}
                  aria-label="고정한 메시지 메뉴"
                  className="grid size-11 shrink-0 place-items-center rounded-full text-ink-soft hover:bg-line/60"
                >
                  <MoreHorizontal size={18} aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-1 flex-col py-4">
        {loadError ? (
          <div className="my-auto space-y-4 py-10 text-center">
            <p className="text-ink-soft">{loadError}</p>
            <div className="flex justify-center">
              <QuietButton onClick={() => setReload((n) => n + 1)}>다시 불러오기</QuietButton>
            </div>
          </div>
        ) : messages === null ? (
          <p className="my-auto py-10 text-center text-ink-soft">대화를 불러오는 중…</p>
        ) : list.length === 0 && !sending ? (
          <div className="my-auto flex flex-col items-center gap-3 py-10 text-center">
            <Avatar partner={partner} size={96} />
            <p className="text-lg font-bold">{partner.name}에게 먼저 인사해 보세요</p>
            <p className="max-w-[28ch] text-ink-soft">영어로 짧게 써도 좋아요. 영어로 뭐라고 하는지 모르면 한국어로 물어봐도 돼요.</p>
          </div>
        ) : (
          <ol aria-label={`${partner.name}와의 대화`} role="log" aria-live="polite" className="flex flex-1 flex-col justify-end">
            {list.map((m, i) => {
              const prev = list[i - 1];
              const next = list[i + 1];
              const at = new Date(m.at);
              const valid = !Number.isNaN(at.getTime());
              const newDay = valid && (!prev || !sameDay(new Date(prev.at), at));
              const startsRun = !prev || prev.role !== m.role || newDay;
              const gapAfter = next && valid ? new Date(next.at).getTime() - at.getTime() > GAP_MS : false;
              const endsRun = !next || next.role !== m.role || gapAfter || (valid && !sameDay(new Date(next.at), at));
              const mine = m.role === 'me';
              return (
                <li key={m.id} id={`msg-${m.id}`} className={newDay ? '' : startsRun ? 'mt-3' : 'mt-1'}>
                  {newDay && <p className="my-4 text-center text-xs font-semibold text-ink-soft">{dayLabel(at, now)}</p>}
                  <div className={`flex items-start gap-2 ${mine ? 'justify-end' : ''}`}>
                    {!mine && <span className="size-8 shrink-0">{startsRun && <Avatar partner={partner} size={32} />}</span>}
                    {mine && (
                      <button
                        type="button"
                        onClick={() => openMenu(m)}
                        aria-label="메시지 메뉴"
                        className="grid size-11 shrink-0 place-items-center self-center rounded-full text-ink-soft hover:bg-line/60"
                      >
                        <MoreHorizontal size={18} aria-hidden />
                      </button>
                    )}
                    <div className={`flex max-w-[80%] flex-col ${mine ? 'items-end' : 'items-start'}`}>
                      <p
                        lang={mine ? undefined : 'en'}
                        {...pressHandlers(m)}
                        style={{ WebkitTouchCallout: 'none' }}
                        className={`rounded-2xl px-4 py-2.5 leading-normal break-words whitespace-pre-wrap ${
                          mine ? `bg-ink text-white ${startsRun ? 'rounded-tr-md' : ''}` : `border border-line bg-surface ${startsRun ? 'rounded-tl-md' : ''}`
                        }`}
                      >
                        <WordText text={m.text} />
                      </p>
                      {(endsRun && valid) || m.pinned ? (
                        <span className="mt-1 flex items-center gap-1 text-xs text-ink-soft">
                          {m.pinned && <Pin size={12} aria-label="고정됨" />}
                          {endsRun && valid && clock(at)}
                        </span>
                      ) : null}
                    </div>
                    {!mine && (
                      <button
                        type="button"
                        onClick={() => openMenu(m)}
                        aria-label="메시지 메뉴"
                        className="grid size-11 shrink-0 place-items-center self-center rounded-full text-ink-soft hover:bg-line/60"
                      >
                        <MoreHorizontal size={18} aria-hidden />
                      </button>
                    )}
                  </div>
                </li>
              );
            })}
            {pending !== null && (
              <>
                <li className="mt-3 flex justify-end">
                  <p className="max-w-[80%] rounded-2xl rounded-tr-md bg-ink/70 px-4 py-2.5 leading-normal break-words whitespace-pre-wrap text-white">{pending}</p>
                </li>
                <li className="mt-3 flex items-center gap-2">
                  <Avatar partner={partner} size={32} />
                  <span className="flex items-center gap-2 rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-2.5 text-sm text-ink-soft">
                    <span aria-hidden className="flex gap-1">
                      <span className="size-1.5 animate-pulse rounded-full bg-ink-soft" />
                      <span className="size-1.5 animate-pulse rounded-full bg-ink-soft [animation-delay:200ms]" />
                      <span className="size-1.5 animate-pulse rounded-full bg-ink-soft [animation-delay:400ms]" />
                    </span>
                    입력 중…
                  </span>
                </li>
              </>
            )}
          </ol>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="sticky bottom-0 z-10 -mx-5 border-t border-line bg-paper/95 px-5 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] backdrop-blur lg:mx-0 lg:px-0 lg:pb-6"
      >
        {error && (
          <p role="alert" className="mb-2 rounded-xl border border-end/40 bg-end/10 px-4 py-2.5 text-sm text-ink">
            {error}
          </p>
        )}
        <div className="flex items-end gap-2">
          <label className="min-w-0 flex-1">
            <span className="sr-only">{partner.name}에게 보낼 메시지</span>
            <textarea
              ref={textarea}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                armIdle();
              }}
              onKeyDown={onKeyDown}
              readOnly={sending}
              aria-busy={sending}
              rows={1}
              maxLength={MAX_LENGTH}
              placeholder="메시지 쓰기"
              enterKeyHint="send"
              className="block max-h-40 min-h-12 w-full resize-none rounded-3xl border border-line bg-surface px-4 py-3 text-base leading-6 text-ink placeholder:text-ink-soft focus:border-ink"
            />
          </label>
          <button
            type="submit"
            aria-label="보내기"
            disabled={sending || !ready || !draft.trim()}
            className="grid size-12 shrink-0 place-items-center rounded-full bg-ink text-white disabled:cursor-not-allowed disabled:bg-ink-soft/40"
          >
            <SendHorizontal size={22} aria-hidden />
          </button>
        </div>
        {draft.length >= MAX_LENGTH - 100 && (
          <p className="mt-1 pr-1 text-right text-xs text-ink-soft">
            {draft.length}/{MAX_LENGTH}
          </p>
        )}
      </form>
      {menu && (
        <div className="fixed inset-0 z-30 flex items-end justify-center bg-ink/40" onClick={() => !menuBusy && setMenu(null)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="메시지 메뉴"
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-[480px] rounded-t-3xl bg-surface px-5 pt-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-lg"
          >
            <p lang={menu.role === 'me' ? undefined : 'en'} className="mb-3 line-clamp-2 border-b border-line pb-3 text-sm text-ink-soft">
              {menu.text}
            </p>
            {menuError && (
              <p role="alert" className="mb-2 rounded-xl border border-end/40 bg-end/10 px-4 py-2.5 text-sm text-ink">
                {menuError}
              </p>
            )}
            {confirmDelete ? (
              <div className="space-y-3">
                <p className="font-semibold">이 메시지를 지울까요?</p>
                <p className="text-sm text-ink-soft">지우면 되돌릴 수 없어요. 친구도 이 메시지를 이어서 보지 않아요.</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={menuBusy}
                    onClick={() => setConfirmDelete(false)}
                    className="min-h-12 flex-1 rounded-full border border-line font-semibold text-ink hover:bg-paper"
                  >
                    취소
                  </button>
                  <button
                    type="button"
                    disabled={menuBusy}
                    onClick={() => void removeMessage(menu)}
                    className="min-h-12 flex-1 rounded-full bg-end font-semibold text-white hover:bg-end-press disabled:opacity-60"
                  >
                    지우기
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col">
                <button
                  type="button"
                  disabled={menuBusy}
                  onClick={() => void togglePin(menu)}
                  className="flex min-h-12 items-center gap-3 rounded-xl px-2 text-left font-semibold text-ink hover:bg-paper"
                >
                  {menu.pinned ? <PinOff size={20} aria-hidden /> : <Pin size={20} aria-hidden />}
                  {menu.pinned ? '고정 풀기' : '맨 위에 고정'}
                </button>
                <button
                  type="button"
                  disabled={menuBusy}
                  onClick={() => setConfirmDelete(true)}
                  className="flex min-h-12 items-center gap-3 rounded-xl px-2 text-left font-semibold text-end hover:bg-paper"
                >
                  <Trash2 size={20} aria-hidden />
                  지우기
                </button>
                <button
                  type="button"
                  onClick={() => setMenu(null)}
                  className="mt-1 min-h-12 rounded-full border border-line font-semibold text-ink hover:bg-paper"
                >
                  닫기
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

export function Chat({
  partnerId,
  brief,
  interests,
  wordbook,
  profileReady,
  onCall,
}: {
  partnerId: string | null;
  brief: string;
  interests?: string[];
  wordbook?: Wordbook | null;
  profileReady: boolean;
  onCall: (partnerId: string) => void;
}) {
  const partner = visibleFriends().find((p) => p.id === partnerId);
  useEffect(() => {
    if (!partner) go('home', true);
  }, [partner]);
  if (!partner) return null;
  return <Conversation key={partner.id} partner={partner} brief={brief} interests={interests} wordbook={wordbook} profileReady={profileReady} onCall={onCall} />;
}
