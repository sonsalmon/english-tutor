import { Star } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ReadglossOffError, saveWord, type SaveSource } from '../lib/api';
import { glossPhrase, isPhraseSaved, isWordSaved, markWordSaved, onSaved as subscribeSaved, savedKey, savePhrase } from '../lib/phrases';
import { lookupForm } from '../lib/units';

type Status = 'idle' | 'saving' | 'saved' | 'off' | 'error';

let offNoticeShown = false;

export function StarButton({
  kind,
  text,
  gloss = '',
  sentence = '',
  source,
  lemma,
  disabled = false,
  saved = false,
  onSaved,
}: {
  kind: 'word' | 'phrase';
  text: string;
  gloss?: string;
  sentence?: string;
  source?: SaveSource;
  lemma?: string;
  disabled?: boolean;
  // 같은 항목을 다른 버튼이 이미 저장했으면 true로 넘겨 채운 별로 맞춘다.
  saved?: boolean;
  onSaved?: () => void;
}) {
  const word = kind === 'word' ? lookupForm(text.trim()) : null;
  const wordKey = (lemma ?? word ?? '').toLowerCase();
  const [status, setStatus] = useState<Status>(() => (kind === 'word' && isWordSaved(wordKey) ? 'saved' : 'idle'));
  const myKey = savedKey(kind, kind === 'word' ? wordKey : text);
  const [message, setMessage] = useState('');
  const onSavedRef = useRef(onSaved);
  onSavedRef.current = onSaved;

  useEffect(() => {
    if (kind !== 'phrase') return;
    let cancelled = false;
    isPhraseSaved(text).then(
      (yes) => {
        if (!cancelled && yes) setStatus('saved');
      },
      () => {},
    );
    return () => {
      cancelled = true;
    };
  }, [kind, text]);

  useEffect(() => subscribeSaved((key) => key === myKey && setStatus('saved')), [myKey]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(''), 4000);
    return () => clearTimeout(timer);
  }, [message]);

  if (kind === 'word' && !word) return null;
  const done = saved || status === 'saved';

  async function save() {
    if (done || disabled || status === 'saving' || status === 'off') return;
    setStatus('saving');
    setMessage('');
    try {
      if (kind === 'word') {
        await saveWord({ word: word!, lemma: wordKey, gloss, sentence, source });
        markWordSaved(wordKey);
      } else {
        await savePhrase(text, (gloss || (await glossPhrase(text))).trim().slice(0, 300), { sentence: sentence || undefined, source });
      }
      setStatus('saved');
      onSavedRef.current?.();
    } catch (e) {
      if (e instanceof ReadglossOffError) {
        setStatus('off');
        if (!offNoticeShown) {
          offNoticeShown = true;
          setMessage('readgloss가 꺼져 있어 저장할 수 없어요.');
        }
      } else {
        setStatus('error');
        setMessage('저장하지 못했어요.');
      }
    }
  }

  const label = done
    ? `저장됨, ${text}`
    : status === 'off'
      ? `readgloss가 꺼져 있어 저장할 수 없어요, ${text}`
      : `단어장에 저장, ${text}`;
  const tone = done ? 'border-call bg-call/10 text-ink' : 'border-line bg-surface text-ink hover:bg-paper disabled:text-ink-soft/50';

  return (
    <span className="relative inline-flex shrink-0">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void save();
        }}
        disabled={done || disabled || status === 'saving' || status === 'off'}
        aria-pressed={done}
        aria-label={label}
        className={`grid size-11 place-items-center rounded-full border ${tone}`}
      >
        <Star size={20} aria-hidden fill={done || status === 'saving' ? 'currentColor' : 'none'} />
      </button>
      {message && (
        <span role="alert" className="absolute top-full right-0 z-10 mt-1 w-max max-w-[220px] rounded-lg bg-ink px-2.5 py-1.5 text-xs leading-snug text-white">
          {message}
        </span>
      )}
    </span>
  );
}
