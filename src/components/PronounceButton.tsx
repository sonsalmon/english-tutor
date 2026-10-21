import { Volume2 } from 'lucide-react';
import { useRef, useState } from 'react';
import { YouGlishSheet } from './YouGlishSheet';

export function PronounceButton({ phrase }: { phrase: string }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);

  function close() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`발음 듣기, ${phrase}`}
        aria-haspopup="dialog"
        className="-my-1 flex min-h-11 shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:bg-paper"
      >
        <Volume2 size={18} aria-hidden />
        발음 듣기
      </button>
      {open && <YouGlishSheet phrase={phrase} onClose={close} />}
    </>
  );
}
