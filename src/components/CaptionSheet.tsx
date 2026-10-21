import { Minus, Plus, X } from 'lucide-react';
import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { formatSync, stepSync } from '../lib/captionTune';
import type { EngMode, TextSize } from '../lib/playerPrefs';

export const CHIP = 'flex min-h-11 items-center justify-center gap-1.5 rounded-full border-2 px-3 text-sm font-semibold whitespace-nowrap';
export const CHIP_ON = 'border-marker bg-marker/15 text-surface';
export const CHIP_OFF = 'border-surface/30 text-surface/80 hover:bg-surface/10';

export const ENG_LABEL: Record<EngMode, string> = { show: '보임', blur: '흐림', hide: '숨김' };
export const SIZE_LABEL: Record<TextSize, string> = { sm: '작게', md: '보통', lg: '크게' };
const ENG_MODES: readonly EngMode[] = ['show', 'blur', 'hide'];
const SIZES: readonly TextSize[] = ['sm', 'md', 'lg'];

// 싱크 -0.1초 / 값(누르면 0으로) / +0.1초. 양수는 자막을 늦춘다.
export function SyncControl({ syncMs, onChange, hint }: { syncMs: number; onChange: (ms: number) => void; hint?: ReactNode }) {
  return (
    <div role="group" aria-label="자막 싱크" className="flex items-center gap-2">
      <button type="button" onClick={() => onChange(stepSync(syncMs, -1))} aria-label="자막 0.1초 당기기" className={`${CHIP} ${CHIP_OFF} size-11 px-0`}>
        <Minus size={18} aria-hidden />
      </button>
      <button
        type="button"
        onClick={() => onChange(0)}
        disabled={syncMs === 0}
        aria-label={syncMs === 0 ? '싱크 0.0초' : `싱크 ${formatSync(syncMs)}, 누르면 0으로`}
        className={`${CHIP} min-w-24 ${syncMs !== 0 ? CHIP_ON : CHIP_OFF} disabled:opacity-100`}
      >
        <span aria-live="polite">싱크 {formatSync(syncMs)}</span>
        {hint}
      </button>
      <button type="button" onClick={() => onChange(stepSync(syncMs, 1))} aria-label="자막 0.1초 늦추기" className={`${CHIP} ${CHIP_OFF} size-11 px-0`}>
        <Plus size={18} aria-hidden />
      </button>
    </div>
  );
}

function Choice<T extends string>({ label, value, options, names, onChange }: { label: string; value: T; options: readonly T[]; names: Record<T, string>; onChange: (v: T) => void }) {
  return (
    <div role="group" aria-label={label} className="grid grid-cols-3 gap-2">
      {options.map((o) => (
        <button key={o} type="button" onClick={() => onChange(o)} aria-pressed={value === o} className={`${CHIP} ${value === o ? CHIP_ON : CHIP_OFF}`}>
          {names[o]}
        </button>
      ))}
    </div>
  );
}

// 폰의 CC 시트: 영어 자막, 글자 크기, 싱크를 한 곳에서 바꾼다. 재생은 멈추지 않는다(싱크를 귀로 맞춰 보려고).
export function CaptionSheet({
  eng,
  size,
  syncMs,
  onEng,
  onSize,
  onSync,
  onClose,
}: {
  eng: EngMode;
  size: TextSize;
  syncMs: number;
  onEng: (v: EngMode) => void;
  onSize: (v: TextSize) => void;
  onSync: (ms: number) => void;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const closeNow = useRef(onClose);
  closeNow.current = onClose;

  useEffect(() => {
    closeRef.current?.focus();
    // 공부 화면의 Esc(화면 닫기)까지 같이 실행되지 않게 여기서 멈춘다.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      closeNow.current();
    };
    const onPointer = (e: PointerEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) closeNow.current();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = panelRef.current.querySelectorAll<HTMLElement>('button:not(:disabled)');
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
    <div className="study fixed inset-0 z-40 flex items-end justify-center">
      <div className="absolute inset-0 bg-ink/30" aria-hidden />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="자막 설정"
        onKeyDown={onKeyDown}
        className="relative w-full max-w-[480px] rounded-t-3xl border-t border-surface/30 bg-ink px-5 pt-4 pb-[calc(20px+env(safe-area-inset-bottom))] text-surface shadow-2xl"
      >
        <div className="flex items-center gap-2">
          <h2 className="min-w-0 flex-1 text-lg font-bold">자막 설정</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="닫기" className="-mr-2 grid size-11 shrink-0 place-items-center rounded-full hover:bg-surface/15">
            <X size={22} aria-hidden />
          </button>
        </div>
        <div className="mt-2 space-y-4">
          <section aria-label="영어 자막">
            <p className="mb-2 text-sm text-surface/80">영어 자막</p>
            <Choice label="영어 자막" value={eng} options={ENG_MODES} names={ENG_LABEL} onChange={onEng} />
          </section>
          <section aria-label="글자 크기">
            <p className="mb-2 text-sm text-surface/80">글자 크기</p>
            <Choice label="글자 크기" value={size} options={SIZES} names={SIZE_LABEL} onChange={onSize} />
          </section>
          <section aria-label="싱크">
            <p className="mb-2 text-sm text-surface/80">자막이 소리보다 빠르면 +, 느리면 -로 맞춰요.</p>
            <SyncControl syncMs={syncMs} onChange={onSync} />
          </section>
        </div>
      </div>
    </div>,
    document.body,
  );
}
