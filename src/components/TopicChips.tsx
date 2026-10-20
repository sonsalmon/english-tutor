export type TopicChip = {
  id: string;
  label: string;
  /** 지시문에 들어가는 영어 주제. 없으면 주제를 정하지 않는다 */
  value?: string;
};

// 오늘 이야기할 주제 고르기. 네이티브 라디오라 방향키와 스크린 리더가 그대로 동작한다.
export function TopicChips({ chips, value, onChange }: { chips: TopicChip[]; value: string; onChange: (id: string) => void }) {
  return (
    <fieldset className="mt-5 min-w-0 lg:mt-6">
      <legend className="mb-2 font-bold">오늘 어떤 이야기를 할까요?</legend>
      <div className="flex flex-wrap gap-2">
        {chips.map((c) => (
          <label key={c.id} className="relative block max-w-full">
            <input type="radio" name="topic-chip" value={c.id} checked={value === c.id} onChange={() => onChange(c.id)} className="peer sr-only" />
            <span className="flex min-h-11 max-w-full cursor-pointer items-center rounded-full border border-line bg-surface px-4 text-left peer-checked:border-ink peer-checked:bg-ink peer-checked:font-semibold peer-checked:text-white peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink/45">
              {c.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
