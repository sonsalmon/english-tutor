import { MicVocal } from 'lucide-react';
import { micNoticeText, type MicState } from '../lib/callux';

export function CallMicNotice({ state }: { state: MicState }) {
  const text = micNoticeText(state);
  if (!text) return null;
  return (
    <p role="status" className="mt-3 flex max-w-xs items-start gap-2 rounded-2xl border border-line bg-surface px-4 py-2 text-left text-sm text-ink-soft">
      <MicVocal size={16} aria-hidden className="mt-0.5 shrink-0" />
      {text}
    </p>
  );
}
