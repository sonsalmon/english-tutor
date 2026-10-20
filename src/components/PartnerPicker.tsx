import { Check } from 'lucide-react';
import { isPark, PARTNERS, partnerMeta } from '../lib/partners';

// 폰에서는 옆으로 밀어 고르는 카드 줄, 넓은 화면에서는 2열 격자. 네이티브 라디오라 방향키와 스크린 리더가 그대로 동작한다.
export function PartnerPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-3 text-lg font-bold lg:mb-4 lg:text-xl">누구와 이야기할까요?</legend>
      <div className="flex snap-x scroll-px-1 gap-3 overflow-x-auto p-1 pb-2 lg:grid lg:grid-cols-2 lg:overflow-visible lg:pb-1">
        {PARTNERS.map((p) => (
          <label key={p.id} className="relative block w-40 shrink-0 snap-start lg:w-auto">
            <input
              type="radio"
              name="partner"
              value={p.id}
              checked={value === p.id}
              onChange={() => onChange(p.id)}
              className="peer sr-only"
            />
            <span className="flex h-full cursor-pointer flex-col gap-2 rounded-2xl border border-line bg-surface p-3 peer-checked:border-ink peer-checked:ring-2 peer-checked:ring-ink peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink/45 lg:flex-row lg:items-start lg:gap-3 lg:p-3 lg:[&_.more]:sr-only lg:peer-checked:[&_.more]:not-sr-only">
              <span className="size-16 shrink-0 overflow-hidden rounded-full bg-line lg:size-14">
                <img src={p.portrait} alt="" width={64} height={64} className={`size-full object-cover ${isPark(p) ? '' : 'scale-[1.15]'}`} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-bold">{p.name}</span>
                <span className="block text-sm text-ink-soft">{partnerMeta(p)}</span>
                <span className="more">
                  <span className="mt-1 block text-sm">{p.intro}</span>
                  <span className="mt-1 block text-sm text-ink-soft">말 속도: {p.paceKo}</span>
                </span>
              </span>
              {value === p.id && (
                <span className="absolute top-2 right-2 grid size-6 place-items-center rounded-full bg-ink text-white" aria-hidden>
                  <Check size={14} />
                </span>
              )}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
