import { Check, X } from 'lucide-react';
import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { CallButton, QuietButton, Screen, TopBar } from '../components/ui';
import { checkDrillAnswer, DrillRequestError, getDrill, type Drill as DrillData, type DrillCheck, type DrillQuestion } from '../lib/apiDrill';
import { friendlyError } from '../lib/errors';
import { PARK_ID } from '../lib/partners';
import { go } from '../lib/router';

const ASK: Record<DrillQuestion['type'], string> = {
  blank: '빈칸에 들어갈 말을 써요',
  choice: '알맞은 말을 골라요',
  rephrase: '자연스러운 문장으로 고쳐 써요',
};

function leave() {
  go('person', false, PARK_ID);
}

// 문장 속 ____ 자리를 눈에 띄는 칸으로 바꿔 보여 준다.
function Sentence({ text, filled }: { text: string; filled?: string }) {
  const parts = text.split('____');
  return (
    <p lang="en" className="text-[22px] leading-snug font-bold">
      {parts.map((part, i) => (
        <span key={i}>
          {part}
          {i < parts.length - 1 && (
            <span className="mx-0.5 inline-block min-w-16 border-b-[3px] border-ink px-1 text-center align-baseline">{filled ? <span className="mark">{filled}</span> : <span aria-label="빈칸">&nbsp;</span>}</span>
          )}
        </span>
      ))}
    </p>
  );
}

function Result({ result, last, onNext }: { result: DrillCheck; last: boolean; onNext: () => void }) {
  const ok = result.correct;
  return (
    <section className="mt-5" aria-live="polite">
      <div className={`rounded-2xl border p-5 ${ok ? 'border-call/40 bg-call/10' : 'border-end/40 bg-end/10'}`}>
        <p className={`flex items-center gap-2 text-lg font-bold ${ok ? 'text-call-press' : 'text-end-press'}`}>
          {ok ? <Check size={22} aria-hidden /> : <X size={22} aria-hidden />}
          {ok ? '맞았어요' : '아쉬워요'}
        </p>
        {!ok && (
          <p className="mt-3 text-[15px]">
            <span className="text-ink-soft">정답 </span>
            <span lang="en" className="font-semibold">
              {result.answer}
            </span>
          </p>
        )}
        <p className="mt-3 leading-relaxed">{result.explanation}</p>
        {result.loose && <p className="mt-3 text-sm leading-relaxed text-ink-soft">뜻이 같고 문법이 맞으면 달라도 괜찮아요. 예시 답과 비교해 보세요.</p>}
      </div>
      <div className="mt-4">
        <CallButton onClick={onNext}>{last ? '결과 보기' : '다음 문제'}</CallButton>
      </div>
    </section>
  );
}

function Question({
  question,
  index,
  total,
  date,
  onDone,
}: {
  question: DrillQuestion;
  index: number;
  total: number;
  date: string;
  onDone: (correct: boolean) => void;
}) {
  const [text, setText] = useState('');
  const [picked, setPicked] = useState<string | null>(null);
  const [result, setResult] = useState<DrillCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (question.type !== 'choice') input.current?.focus({ preventScroll: true });
  }, [question.id, question.type]);

  const submit = useCallback(
    async (answer: string) => {
      if (busy || result || !answer.trim()) return;
      setBusy(true);
      setError(null);
      try {
        setResult(await checkDrillAnswer(date, question.id, answer));
      } catch (e) {
        setError(friendlyError(e, '답을 확인하지 못했어요.'));
      } finally {
        setBusy(false);
      }
    },
    [busy, result, date, question.id],
  );

  const shown = question.type === 'choice' ? picked : null;
  return (
    <>
      <p className="text-sm font-semibold text-ink-soft">
        {index + 1} / {total} · {ASK[question.type]}
      </p>
      <section className="mt-3 rounded-2xl border border-line bg-surface p-5 lg:p-6">
        {question.type === 'rephrase' ? (
          <p lang="en" className="text-[22px] leading-snug font-bold">
            {question.prompt}
          </p>
        ) : (
          <Sentence text={question.prompt} filled={shown ?? (question.type === 'blank' && result ? text.trim() : undefined)} />
        )}
      </section>

      {question.type === 'choice' ? (
        <ul className="mt-4 grid gap-3">
          {(question.options ?? []).map((option) => {
            const isPicked = picked === option;
            const isAnswer = result !== null && result.answer === option;
            const state = result
              ? isAnswer
                ? 'border-call bg-call/10'
                : isPicked
                  ? 'border-end bg-end/10'
                  : 'border-line bg-surface opacity-60'
              : 'border-line bg-surface active:bg-paper';
            return (
              <li key={option}>
                <button
                  type="button"
                  lang="en"
                  disabled={busy || result !== null}
                  onClick={() => {
                    setPicked(option);
                    void submit(option);
                  }}
                  className={`flex min-h-14 w-full items-center rounded-2xl border-2 px-5 text-left text-lg font-semibold ${state}`}
                >
                  {option}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <form
          className="mt-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit(text);
          }}
        >
          <label htmlFor="drill-answer" className="sr-only">
            내 답
          </label>
          <input
            id="drill-answer"
            ref={input}
            lang="en"
            value={text}
            onChange={(e) => setText(e.target.value)}
            readOnly={result !== null}
            autoCapitalize="off"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="done"
            placeholder={question.type === 'blank' ? '들어갈 말' : '고쳐 쓴 문장'}
            className="min-h-14 w-full rounded-2xl border-2 border-line bg-surface px-5 text-[17px] outline-none focus:border-ink"
          />
          {!result && (
            <div className="mt-3">
              <QuietButton onClick={() => void submit(text)}>{busy ? '확인하는 중이에요' : '확인'}</QuietButton>
            </div>
          )}
        </form>
      )}

      {error && (
        <p role="alert" className="mt-3 text-end-press">
          {error}
        </p>
      )}
      {result && <Result result={result} last={index + 1 === total} onNext={() => onDone(result.correct)} />}
    </>
  );
}

function Finish({ right, total }: { right: number; total: number }) {
  return (
    <section className="mt-6 rounded-2xl border border-line bg-surface p-6 text-center" aria-live="polite">
      <p className="text-sm font-semibold text-ink-soft">오늘의 드릴 끝</p>
      <p className="mt-2 text-[40px] leading-none font-bold">
        {right} / {total}
      </p>
      <p className="mt-3 leading-relaxed">{right === total ? '다 맞았어요. 통화에서도 써 보세요.' : '틀린 표현은 통화에서 한 번 더 써 보세요.'}</p>
      <p className="mt-2 text-sm text-ink-soft">내일 새 문제가 열려요.</p>
      <div className="mt-5">
        <CallButton onClick={leave}>Ms. Park 페이지로</CallButton>
      </div>
    </section>
  );
}

export function Drill({ embedded = false }: { embedded?: boolean }) {
  const [drill, setDrill] = useState<DrillData | null>(null);
  const [error, setError] = useState<DrillRequestError | Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [index, setIndex] = useState(0);
  const [right, setRight] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    getDrill(controller.signal).then(setDrill, (e) => {
      if (!controller.signal.aborted) setError(e);
    });
    return () => controller.abort();
  }, [attempt]);

  const total = drill?.questions.length ?? 0;
  const finished = drill !== null && index >= total;
  const retryable = !(error instanceof DrillRequestError && error.status === 409);
  const Frame = embedded ? Fragment : Screen;

  return (
    <Frame>
      <TopBar title="문법 미니 드릴" onBack={leave} />
      {error ? (
        <section className="mt-2 rounded-2xl border border-line bg-surface p-5" role="alert">
          <p className="leading-relaxed">{friendlyError(error, '문제를 불러오지 못했어요.')}</p>
          <div className="mt-4">{retryable ? <QuietButton onClick={() => setAttempt((n) => n + 1)}>다시 시도</QuietButton> : <QuietButton onClick={leave}>돌아가기</QuietButton>}</div>
        </section>
      ) : drill === null ? (
        <p className="mt-2 text-ink-soft" aria-live="polite">
          오늘의 문제를 만드는 중이에요. 처음 열 때만 몇 초 걸려요.
        </p>
      ) : finished ? (
        <Finish right={right} total={total} />
      ) : (
        <Question
          key={drill.questions[index].id}
          question={drill.questions[index]}
          index={index}
          total={total}
          date={drill.date}
          onDone={(correct) => {
            if (correct) setRight((n) => n + 1);
            setIndex((n) => n + 1);
          }}
        />
      )}
    </Frame>
  );
}
