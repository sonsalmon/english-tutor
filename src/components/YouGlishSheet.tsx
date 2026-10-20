import { ExternalLink, X } from 'lucide-react';
import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

// YouGlish 임베드 페이지를 iframe으로만 띄운다. 공식 widget.js는 이 앱과 같은 출처에서 실행되어
// 유료 통화(/api/offer)와 통화 기록 API에 닿을 수 있다. iframe 안의 YouGlish 코드는 자기 출처에만 머문다.
// 이 주소는 widget.js가 만드는 iframe과 같고, 결과가 없으면 YouGlish가 직접 "No result found"를 보여 준다.
function embedUrl(phrase: string): string {
  return `https://youglish.com/pronounce/${encodeURIComponent(phrase)}/english/us/emb=1&e_comp=8`;
}

export function YouGlishSheet({ phrase, onClose }: { phrase: string; onClose: () => void }) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
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

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = panelRef.current.querySelectorAll<HTMLElement>('button, a[href], iframe');
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

        <iframe
          src={embedUrl(query)}
          title={`원어민이 "${query}"를 말하는 영상`}
          allow="autoplay; encrypted-media; picture-in-picture"
          sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
          referrerPolicy="no-referrer"
          className="mt-4 h-[min(480px,55dvh)] w-full rounded-2xl border border-line bg-paper"
        />

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
