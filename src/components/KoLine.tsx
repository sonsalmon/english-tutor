import type { KoLine as KoLineState } from '../lib/useKoLines';

const LINK = 'inline-flex min-h-11 items-center rounded-full px-3 text-sm font-semibold underline';

export function KoLine({ line }: { line: KoLineState }) {
  const { view, ko, reveal, retry } = line;
  if (view === 'off') return null;
  return (
    <div className="mt-3 border-t border-surface/20 pt-2">
      {view === 'hidden' && (
        <button type="button" onClick={reveal} aria-label="한국어 뜻 보기" className={`${LINK} -ml-3 text-surface/90`}>
          한국어 뜻 보기
        </button>
      )}
      {view === 'loading' && (
        <div role="status" aria-label="번역하는 중" className="flex min-h-11 items-center">
          <span className="block h-5 w-2/3 animate-pulse rounded bg-surface/20" />
        </div>
      )}
      {view === 'text' && (
        <p key={ko} lang="ko" className="line-in min-h-11 py-1.5 text-lg leading-snug break-words text-surface/90">
          {ko}
        </p>
      )}
      {view === 'error' && (
        <p role="status" className="flex min-h-11 flex-wrap items-center gap-x-2 text-sm text-surface/80">
          번역을 못 가져왔어요.
          <button type="button" onClick={retry} className={LINK}>
            다시 시도
          </button>
        </p>
      )}
      {view === 'capped' && (
        <p role="status" className="flex min-h-11 flex-wrap items-center gap-x-2 text-sm text-surface/80">
          오늘 번역 한도를 다 썼어요. 내일 다시 볼 수 있어요.
          <button type="button" onClick={retry} className={LINK}>
            다시 시도
          </button>
        </p>
      )}
      {view === 'unavailable' && (
        <p role="status" className="flex min-h-11 items-center text-sm text-surface/80">
          서버에서 한국어 번역이 꺼져 있어요.
        </p>
      )}
    </div>
  );
}
