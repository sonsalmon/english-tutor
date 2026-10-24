import { Send } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { SHARE_MAX } from '../lib/share';

export function ShareRow({ onSend, disabled = false }: { onSend: (text: string) => boolean; disabled?: boolean }) {
  const [text, setText] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!disabled && onSend(text)) setText('');
  };
  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <input
        type="text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        maxLength={SHARE_MAX}
        enterKeyHint="send"
        autoComplete="off"
        autoCapitalize="off"
        disabled={disabled}
        aria-label="보낼 메시지나 링크"
        placeholder="보낼 메시지나 링크"
        className="h-12 min-w-0 flex-1 rounded-full border border-line bg-surface px-4 text-base text-ink placeholder:text-ink-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink disabled:opacity-50"
      />
      <button
        type="submit"
        aria-label="보내기"
        disabled={disabled || !text.trim()}
        className="grid size-12 shrink-0 place-items-center rounded-full bg-ink text-white disabled:opacity-40"
      >
        <Send size={20} aria-hidden />
      </button>
    </form>
  );
}
