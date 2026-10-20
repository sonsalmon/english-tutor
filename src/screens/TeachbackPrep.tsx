import { Phone } from 'lucide-react';
import { useEffect, useState } from 'react';
import { CallButton, Screen, TopBar } from '../components/ui';
import { getLesson, type Lesson } from '../lib/api';
import type { SeniorMode } from '../lib/instructions';
import { go } from '../lib/router';

const SENIOR_KEY = 'teachback.seniorMode';
const EMPTY_MESSAGE = '이 날짜는 보낼 수 있는 내용이 없어요(거름망에 모두 걸림)';

function readSeniorMode(): SeniorMode {
  try {
    return localStorage.getItem(SENIOR_KEY) === 'after' ? 'after' : 'during';
  } catch {
    return 'during';
  }
}

function snippet(body?: string): string {
  const text = (body || '').replace(/\s+/g, ' ').trim();
  return text.length > 90 ? `${text.slice(0, 90)}…` : text;
}

export function TeachbackPrep({ onStart }: { onStart: (lesson: Lesson, seniorMode: SeniorMode) => void }) {
  const [date, setDate] = useState<string | undefined>(undefined);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seniorMode, setSeniorMode] = useState<SeniorMode>(readSeniorMode);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getLesson(date, controller.signal)
      .then(setLesson)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '수업 기록을 불러오지 못했어요.');
      });
    return () => controller.abort();
  }, [date]);

  const chooseSenior = (mode: SeniorMode) => {
    setSeniorMode(mode);
    try {
      localStorage.setItem(SENIOR_KEY, mode);
    } catch {
      // 저장하지 못해도 이번 수업 설정은 그대로 쓴다.
    }
  };

  const options = ['during', 'after'] as const;
  const onRadioKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = options[(options.indexOf(seniorMode) + step + options.length) % options.length];
    chooseSenior(next);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-value="${next}"]`)?.focus();
  };

  const canStart = !!lesson && lesson.sections.length > 0;

  return (
    <Screen>
      <TopBar title="가르치며 배우기" onBack={() => go('home')} />
      <p className="leading-relaxed text-ink-soft">
        오늘 공부한 내용을 영어로 설명해요. 미국 중학생 Maya, Leo, Sam이 모르는 말을 물어봐요. 모르면 “Good question - let me check and get back to you.”라고 하면 돼요.
      </p>

      <section className="mt-6 rounded-2xl border border-line bg-surface p-5">
        {error ? (
          <p className="text-end-press">{error}</p>
        ) : !lesson ? (
          <p className="text-ink-soft">수업 기록을 불러오는 중이에요.</p>
        ) : (
          <>
            <label htmlFor="lesson-date" className="text-sm font-semibold text-ink-soft">
              수업 날짜
            </label>
            <select
              id="lesson-date"
              value={lesson.date}
              onChange={(e) => setDate(e.target.value)}
              className="mt-1 block min-h-11 w-full rounded-xl border border-line bg-paper px-3 font-semibold"
            >
              {(lesson.dates.length ? lesson.dates : [lesson.date]).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <h2 className="mt-4 text-lg font-bold">{lesson.day_title || '제목 없음'}</h2>
            {lesson.hidden_count ? (
              <p className="mt-1 text-sm text-ink-soft">차단어로 가린 절 {lesson.hidden_count}개는 제외했어요.</p>
            ) : null}
            {lesson.sections.length ? (
              <ul className="mt-3 space-y-3">
                {lesson.sections.map((s, i) => (
                  <li key={i}>
                    <p className="font-semibold">{s.heading || '(제목 없음)'}</p>
                    <p className="text-sm text-ink-soft">{snippet(s.body)}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-end-press">{EMPTY_MESSAGE}</p>
            )}
          </>
        )}
      </section>

      <fieldset className="mt-6">
        <legend id="senior-legend" className="font-semibold">Ms. Park은 언제 도와줄까요?</legend>
        <div className="mt-2 grid grid-cols-2 gap-2" role="radiogroup" aria-labelledby="senior-legend" onKeyDown={onRadioKey}>
          {([
            ['during', '수업 중에', '영어가 막히면 바로 한마디'],
            ['after', '수업 끝나고', '수업 중에는 조용히'],
          ] as const).map(([value, title, desc]) => {
            const active = seniorMode === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={active}
                data-value={value}
                tabIndex={active ? 0 : -1}
                onClick={() => chooseSenior(value)}
                className={`min-h-16 rounded-2xl border p-3 text-left ${active ? 'border-ink bg-surface' : 'border-line bg-paper text-ink-soft'}`}
              >
                <span className="block font-semibold">{title}</span>
                <span className="block text-sm">{desc}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-auto pt-8">
        <CallButton disabled={!canStart} onClick={() => lesson && onStart(lesson, seniorMode)}>
          <Phone size={22} aria-hidden />
          수업 시작하기
        </CallButton>
      </div>
    </Screen>
  );
}
