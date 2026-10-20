import { Volume2 } from 'lucide-react';
import { useRef, useState, type ReactNode } from 'react';
import type { Tutoring } from '../lib/api';
import { YouGlishSheet } from './YouGlishSheet';

const CAUSES: Record<string, string> = {
  english: '영어 표현',
  understanding: '내용 이해',
  both: '둘 다',
  unclear: '원인 불분명',
};

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-lg font-bold">{title}</h2>
      <div className="divide-y divide-line rounded-2xl border border-line bg-surface">{children}</div>
    </section>
  );
}

function PronounceButton({ phrase }: { phrase: string }) {
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

export function TutoringBlocks({ tutoring, isTeachback }: { tutoring: Tutoring; isTeachback: boolean }) {
  const retry = tutoring.retry;
  return (
    <>
      {tutoring.corrections.length > 0 && (
        <Block title="고쳐 말하기">
          {tutoring.corrections.map((c, i) => (
            <div key={i} className="p-4">
              <p className="text-ink-soft line-through decoration-ink-soft/50">{c.said}</p>
              <div className="mt-1 flex items-start justify-between gap-3">
                <p className="min-w-0 text-lg font-semibold">
                  <span className="mark">{c.better}</span>
                </p>
                <PronounceButton phrase={c.better} />
              </div>
              {c.why && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{c.why}</p>}
            </div>
          ))}
        </Block>
      )}
      {tutoring.good.length > 0 && (
        <Block title="잘한 표현">
          {tutoring.good.map((g, i) => (
            <div key={i} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 font-semibold">{g.said}</p>
                <PronounceButton phrase={g.said} />
              </div>
              {g.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{g.note}</p>}
            </div>
          ))}
        </Block>
      )}
      {tutoring.vocab.length > 0 && (
        <Block title="기억할 단어">
          {tutoring.vocab.map((v, i) => (
            <div key={i} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0">
                  <span className="font-semibold">{v.word}</span>
                  {v.meaning_ko && <span className="ml-2 text-ink-soft">{v.meaning_ko}</span>}
                </p>
                <PronounceButton phrase={v.word} />
              </div>
              {v.example && <p className="mt-1 text-sm text-ink-soft">{v.example}</p>}
            </div>
          ))}
        </Block>
      )}
      {tutoring.pragmatics.length > 0 && (
        <Block title="미국식으로 말하기">
          {tutoring.pragmatics.map((p, i) => (
            <div key={i} className="p-4">
              <p className="font-semibold">{p.pattern}</p>
              {p.note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{p.note}</p>}
            </div>
          ))}
        </Block>
      )}
      {isTeachback && (tutoring.unanswered?.length ?? 0) > 0 && (
        <Block title="답하지 못한 질문">
          {tutoring.unanswered!.map((u, i) => (
            <div key={i} className="p-4">
              <p className="font-semibold">{u.question}</p>
              {u.evidence && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{u.evidence}</p>}
              <span className="mt-2 inline-block rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">{CAUSES[u.cause] ?? u.cause}</span>
            </div>
          ))}
        </Block>
      )}
      {retry?.goal && (
        <section className="mt-8 rounded-2xl bg-ink p-5 text-white">
          <h2 className="text-sm font-semibold text-white/70">다음 통화 목표</h2>
          <p className="mt-2 leading-relaxed">{retry.goal}</p>
          {!!retry.target_phrases?.length && (
            <p className="mt-3 text-sm text-white/80">{retry.target_phrases.map((p) => `“${p}”`).join('  ')}</p>
          )}
        </section>
      )}
    </>
  );
}
