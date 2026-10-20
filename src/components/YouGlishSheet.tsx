import { ExternalLink, LoaderCircle, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type YGEvent = { totalResult?: number };
type YGWidget = { fetch: (query: string, lang: string, accent?: string) => void };
type YGNamespace = {
  // 위젯은 요소가 아니라 요소 id 문자열을 받는다(공식 예제 new YG.Widget("widget-1", ...)). 요소를 넘기면 영상이 뜨지 않았다.
  Widget: new (
    elementId: string,
    options: { width?: number; components?: number; events?: Record<string, (e: YGEvent) => void> },
  ) => YGWidget;
};

declare global {
  interface Window {
    YG?: YGNamespace;
    onYouglishAPIReady?: () => void;
  }
}

const WIDGET_SRC = 'https://youglish.com/public/emb/widget.js';
const COMPONENTS_CAPTION_ONLY = 8;
const FETCH_TIMEOUT_MS = 15000;

let apiPromise: Promise<YGNamespace> | null = null;

function loadYouGlish(): Promise<YGNamespace> {
  if (window.YG?.Widget) return Promise.resolve(window.YG);
  apiPromise ??= new Promise<YGNamespace>((resolve, reject) => {
    window.onYouglishAPIReady = () => {
      if (window.YG) resolve(window.YG);
      else reject(new Error('YG missing'));
    };
    const script = document.createElement('script');
    script.src = WIDGET_SRC;
    script.async = true;
    script.onerror = () => {
      apiPromise = null;
      script.remove();
      reject(new Error('widget.js load failed'));
    };
    document.head.appendChild(script);
  });
  return apiPromise;
}

type Status = 'loading' | 'ready' | 'empty' | 'error';

const MESSAGES: Record<Exclude<Status, 'ready'>, string> = {
  loading: '원어민이 이 표현을 말하는 영상을 찾고 있어요.',
  empty: '이 표현이 들어간 영상을 찾지 못했어요. YouGlish에서 직접 검색해 보세요.',
  error: '영상을 불러오지 못했어요. YouGlish 사이트에서 열어 보세요.',
};

export function YouGlishSheet({ phrase, onClose }: { phrase: string; onClose: () => void }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const widgetBox = useRef<HTMLDivElement>(null);
  const boxId = `yg-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const [status, setStatus] = useState<Status>('loading');
  const query = phrase.trim();
  const fallbackUrl = `https://youglish.com/pronounce/${encodeURIComponent(query)}/english/us`;

  useEffect(() => {
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    const box = widgetBox.current;
    if (!box) return;
    let cancelled = false;
    let timer: number | undefined;
    setStatus('loading');
    loadYouGlish()
      .then((YG) => {
        if (cancelled) return;
        const widget = new YG.Widget(boxId, {
          width: Math.max(240, box.clientWidth),
          components: COMPONENTS_CAPTION_ONLY,
          events: {
            onFetchDone: (e) => {
              window.clearTimeout(timer);
              if (!cancelled) setStatus(e.totalResult === 0 ? 'empty' : 'ready');
            },
            onError: () => {
              window.clearTimeout(timer);
              if (!cancelled) setStatus('error');
            },
          },
        });
        timer = window.setTimeout(() => {
          if (!cancelled) setStatus('error');
        }, FETCH_TIMEOUT_MS);
        widget.fetch(query, 'english', 'us');
      })
      .catch(() => {
        if (!cancelled) setStatus('error');
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      box.replaceChildren();
    };
  }, [query, boxId]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = panelRef.current.querySelectorAll<HTMLElement>('button, a[href]');
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center" onKeyDown={onKeyDown}>
      <div className="absolute inset-0 bg-ink/40" onClick={onClose} aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="relative max-h-[90dvh] w-full max-w-[480px] overflow-y-auto rounded-t-3xl bg-surface px-5 pt-5 pb-[calc(20px+env(safe-area-inset-bottom))]"
      >
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-sm font-semibold text-ink-soft">
              발음 듣기
            </h2>
            <p lang="en" className="mt-1 text-xl font-bold leading-snug">
              <span className="mark">{query}</span>
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="-mt-1 -mr-2 grid size-11 shrink-0 place-items-center rounded-full text-ink hover:bg-line/60"
          >
            <X size={22} aria-hidden />
          </button>
        </div>

        <div id={boxId} ref={widgetBox} className="mt-4 w-full overflow-hidden rounded-2xl" />

        {status !== 'ready' && (
          <div
            className="mt-4 flex items-center gap-3 text-ink-soft"
            role={status === 'loading' ? 'status' : undefined}
          >
            {status === 'loading' && <LoaderCircle size={20} className="shrink-0 animate-spin" aria-hidden />}
            <p>{MESSAGES[status]}</p>
          </div>
        )}

        <a
          href={fallbackUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 flex min-h-12 w-full items-center justify-center gap-2 rounded-full border border-line bg-surface px-6 font-semibold text-ink hover:bg-paper"
        >
          <ExternalLink size={18} aria-hidden />
          YouGlish에서 열기
        </a>
      </div>
    </div>,
    document.body,
  );
}
