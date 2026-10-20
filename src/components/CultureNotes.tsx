import { useEffect, useState } from 'react';
import { getCallCulture, type CultureBank, type CultureBlend, type CultureResult } from '../lib/api';
import { WordText } from './WordText';

function Answers({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="min-w-0">
      <h5 className="text-sm font-semibold text-ink-soft">{label}</h5>
      <ul lang="en" className="mt-1 space-y-0.5 leading-snug break-words">
        {items.slice(0, 4).map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </div>
  );
}

function BlendRow({ item }: { item: CultureBlend }) {
  return (
    <li className="p-4">
      <p lang="en" className="font-semibold">
        <WordText text={item.question} />
      </p>
      <div className="mt-3 grid grid-cols-2 gap-4">
        <Answers label="한국" items={item.korea} />
        <Answers label="미국" items={item.us} />
      </div>
    </li>
  );
}

const LONG_TEXT = 160;

const SOURCE_LABEL: Record<string, string> = { tiktok: 'TikTok', reddit: 'Reddit' };

function ExtLink({ href, children }: { href: string; children: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:text-ink">
      {children}
    </a>
  );
}

function Credit({ children }: { children: React.ReactNode }) {
  return <p className="mt-2 text-xs leading-relaxed text-ink-soft break-words">{children}</p>;
}

function BankRow({ item }: { item: CultureBank }) {
  const [open, setOpen] = useState(false);
  const place = item.country === 'KR' ? '한국에서는' : '미국에서는';
  const long = item.text.length > LONG_TEXT;
  const source = SOURCE_LABEL[(item.source || '').toLowerCase()];
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{place}</span>
        {item.topic && <span className="rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">{item.topic}</span>}
        {source && <span className="text-xs text-ink-soft">{source}</span>}
      </div>
      <p lang="en" className={`mt-1 leading-relaxed break-words ${long && !open ? 'line-clamp-3' : ''}`}>
        <WordText text={item.text} />
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="-mb-2 mt-1 min-h-11 rounded-full text-sm font-semibold text-ink-soft hover:text-ink"
        >
          {open ? '접기' : '더 보기'}
        </button>
      )}
    </li>
  );
}

export function CultureNotes({ stem }: { stem: string }) {
  const [state, setState] = useState<{ stem: string; data: CultureResult | null }>({ stem: '', data: null });

  useEffect(() => {
    const controller = new AbortController();
    getCallCulture(stem, controller.signal).then(
      (data) => setState({ stem, data }),
      () => {
        // 못 불러오면 이 구역만 숨긴다.
      },
    );
    return () => controller.abort();
  }, [stem]);

  const data = state.stem === stem ? state.data : null;
  if (!data || data.status !== 'ok' || (!data.blend.length && !data.bank.length)) return null;

  return (
    <section className="mt-8" aria-labelledby="culture-notes-title">
      <h3 id="culture-notes-title" className="mb-3 text-lg font-bold">
        한국·미국 차이
      </h3>
      {data.blend.length > 0 && (
        <>
          <h4 className="mb-2 text-sm font-semibold text-ink-soft">같은 질문, 다른 답</h4>
          <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
            {data.blend.map((b) => (
              <BlendRow key={b.id} item={b} />
            ))}
          </ul>
          <Credit>
            BLEnD (<ExtLink href="https://arxiv.org/abs/2406.09948">arXiv 2406.09948</ExtLink>) ·{' '}
            <ExtLink href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</ExtLink> · 상위 답만 골라 보여 줌
          </Credit>
        </>
      )}
      {data.bank.length > 0 && (
        <>
          <ul className={`divide-y divide-line rounded-2xl border border-line bg-surface ${data.blend.length ? 'mt-6' : ''}`}>
            {data.bank.map((b, i) => (
              <BankRow key={i} item={b} />
            ))}
          </ul>
          <Credit>
            CultureBank (<ExtLink href="https://arxiv.org/abs/2404.15238">arXiv 2404.15238</ExtLink>) ·{' '}
            <ExtLink href="https://huggingface.co/datasets/SALT-NLP/CultureBank">MIT</ExtLink> · 원문 일부, 출처 TikTok/Reddit
          </Credit>
        </>
      )}
    </section>
  );
}
