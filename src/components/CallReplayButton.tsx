import { Snail, Square } from 'lucide-react';

export function CallReplayButton({ ready, replaying, onClick }: { ready: boolean; replaying: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!ready && !replaying}
      className="mt-3 flex min-h-11 items-center gap-2 rounded-full border border-line bg-surface px-5 text-sm font-semibold text-ink disabled:text-ink-soft disabled:opacity-60"
    >
      {replaying ? <Square size={16} aria-hidden /> : <Snail size={18} aria-hidden />}
      {replaying ? '다시 듣는 중 (멈추기)' : '느리게 다시 듣기'}
    </button>
  );
}
