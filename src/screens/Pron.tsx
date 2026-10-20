import { AudioLines, Check, Clock, Mic, RotateCcw, Square } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { QuietButton, Screen, TopBar } from '../components/ui';
import { WordText } from '../components/WordText';
import {
  MicError,
  finishPron,
  getPronLatest,
  getPronTest,
  startRecorder,
  transcribePron,
  type PronContrast,
  type PronItem,
  type PronResult,
  type PronTest,
  type Recorder,
} from '../lib/pron';
import { go } from '../lib/router';

const METER_BARS = 14;
const MIN_SECONDS = 0.5;
const MIN_PEAK = 0.01;

function PrimaryButton({ children, onClick, disabled, autoFocus }: { children: ReactNode; onClick: () => void; disabled?: boolean; autoFocus?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      autoFocus={autoFocus}
      className="flex min-h-14 w-full items-center justify-center gap-2 rounded-full bg-ink px-6 text-lg font-bold text-white active:bg-ink/85 disabled:cursor-not-allowed disabled:bg-ink-soft/40 lg:w-auto lg:min-w-64 lg:px-10"
    >
      {children}
    </button>
  );
}

function Meter({ level, active }: { level: number; active: boolean }) {
  const lit = active ? Math.round(level * METER_BARS) : 0;
  return (
    <div aria-hidden className="flex h-6 items-center justify-center gap-1">
      {Array.from({ length: METER_BARS }, (_, i) => (
        <span key={i} className={`h-5 w-1.5 rounded-full transition-colors duration-100 ${i < lit ? 'bg-call' : 'bg-line'}`} />
      ))}
    </div>
  );
}

type Step = 'ready' | 'starting' | 'recording' | 'processing' | 'saved';
type Job = { status: 'pending' | 'done' | 'failed'; text: string; error: string };

// 받아쓰기는 문장마다 몇 초 걸리고 Vertex가 가끔 429로 거절한다. 그래서 뒤에서 한 번에 하나씩 보내고,
// 실패하면 잠시 뒤 다시 보낸다(첫 시도 + 5초 + 15초). 사용자는 기다리지 않고 다음 문장으로 넘어간다.
const RETRY_DELAYS = [0, 5000, 15000];

function Session({ items, onDone, onExit }: { items: PronItem[]; onDone: (result: PronResult) => void; onExit: () => void }) {
  const [index, setIndex] = useState(0);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [step, setStep] = useState<Step>('ready');
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [fixing, setFixing] = useState(false);
  const [review, setReview] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const recorder = useRef<Recorder | null>(null);
  const abort = useRef(new AbortController());
  const version = useRef<Record<string, number>>({});
  const queue = useRef<Promise<void>>(Promise.resolve());
  const stopRef = useRef<() => Promise<void>>(async () => {});

  const item = items[index];
  const last = index === items.length - 1;
  const job = jobs[item.id];

  useEffect(
    () => () => {
      recorder.current?.cancel();
      abort.current.abort();
    },
    [],
  );

  const enqueue = useCallback((id: string, blob: Blob) => {
    const v = (version.current[id] ?? 0) + 1;
    version.current[id] = v;
    const put = (next: Job) => {
      if (version.current[id] === v) setJobs((prev) => ({ ...prev, [id]: next }));
    };
    put({ status: 'pending', text: '', error: '' });
    queue.current = queue.current.then(async () => {
      let lastError = '받아쓰기에 실패했어요.';
      for (const delay of RETRY_DELAYS) {
        if (delay) await new Promise((r) => window.setTimeout(r, delay));
        if (abort.current.signal.aborted || version.current[id] !== v) return;
        try {
          const text = await transcribePron(blob, abort.current.signal);
          put(text ? { status: 'done', text, error: '' } : { status: 'failed', text: '', error: '목소리를 알아듣지 못했어요.' });
          return;
        } catch (e) {
          if (e instanceof DOMException && e.name === 'AbortError') return;
          lastError = e instanceof Error ? e.message : lastError;
        }
      }
      put({ status: 'failed', text: '', error: lastError });
    });
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setStep('starting');
    try {
      recorder.current = await startRecorder(setLevel, () => void stopRef.current());
      setStep('recording');
    } catch (e) {
      setError(e instanceof MicError ? e.message : '마이크를 켜지 못했어요.');
      setStep('ready');
    }
  }, []);

  const stop = useCallback(async () => {
    const active = recorder.current;
    if (!active) return;
    recorder.current = null;
    setLevel(0);
    setStep('processing');
    try {
      const recording = await active.stop();
      if (recording.seconds < MIN_SECONDS) {
        setError('녹음이 너무 짧아요. 문장을 끝까지 읽은 뒤에 멈춰 주세요.');
        setStep('ready');
      } else if (recording.peak < MIN_PEAK) {
        setError('소리가 거의 들리지 않았어요. 마이크가 켜져 있는지 확인하고 다시 읽어 주세요.');
        setStep('ready');
      } else {
        enqueue(item.id, recording.blob);
        setStep('saved');
      }
    } catch {
      setError('녹음을 마무리하지 못했어요. 다시 읽어 주세요.');
      setStep('ready');
    }
  }, [enqueue, item.id]);
  stopRef.current = stop;

  const failedItems = items.filter((it) => jobs[it.id]?.status === 'failed');
  const pendingCount = items.filter((it) => jobs[it.id]?.status === 'pending').length;
  const doneCount = items.filter((it) => jobs[it.id]?.status === 'done').length;
  const recordedCount = items.filter((it) => jobs[it.id]).length;

  const next = () => {
    setError(null);
    setStep('ready');
    if (fixing) {
      const target = items.findIndex((it) => it.id !== item.id && jobs[it.id]?.status === 'failed');
      if (target >= 0) {
        setIndex(target);
      } else {
        setFixing(false);
        setReview(true);
      }
      return;
    }
    if (last) setReview(true);
    else setIndex((i) => i + 1);
  };

  const redo = () => {
    setStep('ready');
    setError(null);
  };

  const finish = useCallback(async () => {
    setFinishing(true);
    setFinishError(null);
    try {
      const list = items.filter((it) => jobs[it.id]?.status === 'done').map((it) => ({ id: it.id, text: jobs[it.id].text }));
      if (!list.length) throw new Error('받아쓴 문장이 없어 결과를 만들 수 없어요.');
      onDone(await finishPron(list));
    } catch (e) {
      setFinishError(e instanceof Error ? e.message : '결과를 만들지 못했어요.');
      setFinishing(false);
    }
  }, [items, jobs, onDone]);

  // 마지막 문장을 넘긴 뒤: 받아쓰기가 모두 끝나고 실패가 없으면 바로 결과를 만든다.
  useEffect(() => {
    if (review && !finishing && !finishError && pendingCount === 0 && failedItems.length === 0) void finish();
  }, [review, finishing, finishError, pendingCount, failedItems.length, finish]);

  if (review) {
    return (
      <Screen>
        <TopBar title="발음 진단" onBack={onExit} />
        <section className="mt-6 rounded-2xl border border-line bg-surface p-6 lg:p-8" aria-live="polite">
          {pendingCount > 0 ? (
            <>
              <p className="text-xl font-bold">받아쓰는 중이에요</p>
              <p className="mt-2 text-ink-soft">
                {items.length}문장 중 {doneCount}문장을 받아썼어요. 남은 {pendingCount}문장이 끝나면 결과를 보여 드려요.
              </p>
            </>
          ) : failedItems.length > 0 && !finishing ? (
            <>
              <p className="text-xl font-bold">받아쓰지 못한 문장이 {failedItems.length}개 있어요</p>
              <ul className="mt-3 space-y-2">
                {failedItems.map((it) => (
                  <li key={it.id} className="text-[15px] leading-relaxed">
                    <span lang="en">{it.text}</span>
                    <span className="block text-sm text-ink-soft">{jobs[it.id].error}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-6 flex flex-col gap-3 lg:flex-row">
                <PrimaryButton
                  autoFocus
                  onClick={() => {
                    setReview(false);
                    setFixing(true);
                    setIndex(items.indexOf(failedItems[0]));
                    setStep('ready');
                  }}
                >
                  이 문장만 다시 녹음하기
                </PrimaryButton>
                <QuietButton onClick={() => void finish()}>빼고 결과 보기</QuietButton>
              </div>
            </>
          ) : (
            <p className="text-xl font-bold">결과를 만드는 중이에요</p>
          )}
          {finishError && (
            <div role="alert" className="mt-4">
              <p className="text-end-press">{finishError}</p>
              <div className="mt-3">
                <QuietButton onClick={() => void finish()}>다시 시도</QuietButton>
              </div>
            </div>
          )}
        </section>
      </Screen>
    );
  }

  const recording = step === 'recording';
  const status =
    step === 'recording'
      ? '녹음 중이에요. 다 읽으면 버튼을 한 번 더 눌러요.'
      : step === 'starting'
        ? '마이크를 켜는 중이에요.'
        : step === 'processing'
          ? '녹음을 정리하는 중이에요.'
          : '버튼을 누르고 위 문장을 읽어요.';
  const nextLabel = fixing ? '다음' : last ? '끝내고 결과 보기' : '다음 문장';

  return (
    <Screen>
      <TopBar title="발음 진단" onBack={onExit} />
      <div className="flex items-center gap-3" aria-label={`진행 ${index + 1} / ${items.length}`}>
        <span className="min-w-14 text-sm font-semibold tabular-nums text-ink-soft">
          {index + 1} / {items.length}
        </span>
        <div className="h-1.5 flex-1 rounded-full bg-line" aria-hidden>
          <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${(recordedCount / items.length) * 100}%` }} />
        </div>
      </div>

      <section className="mt-6 rounded-2xl border border-line bg-surface p-6 lg:p-8">
        <p data-pron-sentence lang="en" className="text-[28px] font-bold leading-snug lg:text-[40px]">
          <WordText text={item.text} />
        </p>
        <p className="mt-4 text-sm text-ink-soft">평소 말하듯 자연스럽게 읽어요. 일부러 또박또박 읽지 않아도 돼요.</p>
      </section>

      <section className="mt-6 flex min-h-56 flex-col items-center justify-start text-center" aria-live="polite">
        {step === 'saved' ? (
          <div className="w-full">
            <p className="text-[15px] leading-relaxed text-ink-soft" data-pron-heard>
              {job?.status === 'done' ? (
                <>
                  들린 대로: <span lang="en" className="text-ink"><WordText text={job.text} /></span>
                </>
              ) : job?.status === 'failed' ? (
                <span className="text-end-press">{job.error} 다시 녹음해 주세요.</span>
              ) : (
                '녹음했어요. 받아쓰기는 뒤에서 이어서 해요.'
              )}
            </p>
            <div className="mt-6 flex flex-col gap-3 lg:flex-row lg:justify-center">
              <PrimaryButton autoFocus onClick={next}>
                {nextLabel}
              </PrimaryButton>
              <QuietButton onClick={redo}>
                <RotateCcw size={18} aria-hidden />
                다시 녹음
              </QuietButton>
            </div>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={recording ? () => void stop() : () => void start()}
              disabled={step === 'starting' || step === 'processing'}
              aria-label={recording ? '녹음 끝' : '녹음 시작'}
              autoFocus={step === 'ready'}
              className={`grid size-24 place-items-center rounded-full text-white shadow-[0_8px_20px_-8px_rgb(20_33_61/0.6)] disabled:cursor-not-allowed disabled:opacity-40 ${
                recording ? 'bg-end active:bg-end-press' : 'bg-ink active:bg-ink/85'
              }`}
            >
              {recording ? <Square size={30} fill="currentColor" aria-hidden /> : <Mic size={38} aria-hidden />}
            </button>
            <div className="mt-4">
              <Meter level={level} active={recording} />
            </div>
            <p className="mt-2 text-ink-soft">{status}</p>
            {error && (
              <p role="alert" className="mt-4 w-full leading-relaxed text-end-press">
                {error}
              </p>
            )}
          </>
        )}
        {recordedCount > 0 && (
          <p className="mt-6 text-sm text-ink-soft" data-pron-queue>
            받아쓰기 {doneCount} / {recordedCount}
            {pendingCount > 0 ? ` · ${pendingCount}개 받아쓰는 중` : ''}
            {failedItems.length > 0 ? ` · ${failedItems.length}개 실패` : ''}
          </p>
        )}
      </section>
    </Screen>
  );
}

function normalize(s: string): string {
  return s.toLowerCase().replace(/’/g, "'");
}

function direction(c: PronContrast): string | null {
  if (c.contrast !== 'can_cant') return null;
  const cantAsCan = c.misheard.filter((m) => normalize(m.target) === "can't").length;
  const canAsCant = c.misheard.filter((m) => normalize(m.target) === 'can').length;
  const parts: string[] = [];
  if (cantAsCan) parts.push(`can't를 can으로 들은 문장 ${cantAsCan}개`);
  if (canAsCant) parts.push(`can을 can't로 들은 문장 ${canAsCant}개`);
  return parts.length ? parts.join(', ') : null;
}

function severity(c: PronContrast): number {
  return c.as_other * 10 + c.unclear;
}

function Bar({ c }: { c: PronContrast }) {
  const pct = (n: number) => `${(n / Math.max(c.total, 1)) * 100}%`;
  return (
    <div
      role="img"
      aria-label={`다르게 들린 문장 ${c.as_other}개, 불분명 ${c.unclear}개, 전체 ${c.total}개`}
      className="flex h-2.5 overflow-hidden rounded-full bg-line"
    >
      <span className="h-full bg-end" style={{ width: pct(c.as_other) }} />
      <span className="h-full bg-marker" style={{ width: pct(c.unclear) }} />
    </div>
  );
}

function ContrastCard({ c }: { c: PronContrast }) {
  const summary = [direction(c) ?? `다르게 들린 문장 ${c.as_other}개`];
  if (c.unclear > 0) summary.push(`정확히 알아듣기 어려운 문장 ${c.unclear}개`);
  const shown = c.misheard.slice(0, 3);
  const unclearAll = c.unclear_heard ?? [];
  const unclearShown = unclearAll.slice(0, 3);
  return (
    <article className="rounded-2xl border border-line bg-surface p-5">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-lg font-bold">
          <WordText text={c.label} />
        </h3>
        <p className="text-xl font-bold tabular-nums">
          {c.as_other}
          <span className="text-ink-soft">/{c.total}</span>
        </p>
      </header>
      <div className="mt-3">
        <Bar c={c} />
      </div>
      <p className="mt-3 text-[15px] leading-relaxed">{summary.join(', ')}</p>
      {shown.length > 0 && (
        <ul className="mt-3 space-y-2">
          {shown.map((m, i) => (
            <li key={i} className="rounded-xl bg-paper px-3 py-2 text-[15px] leading-relaxed">
              <span className="text-ink-soft">읽으려던 단어 </span>
              <span lang="en" className="font-semibold">
                <WordText text={m.target} />
              </span>
              <span className="block text-ink-soft">
                들린 문장: <span lang="en" className="text-ink"><WordText text={m.heard_text} /></span>
              </span>
            </li>
          ))}
          {c.misheard.length > shown.length && <li className="text-sm text-ink-soft">그 밖에 {c.misheard.length - shown.length}개가 더 있어요.</li>}
        </ul>
      )}
      {unclearShown.length > 0 && (
        <div className="mt-3">
          <h4 className="text-sm font-semibold text-ink-soft">알아듣기 어려웠던 문장</h4>
          <ul className="mt-2 space-y-2">
            {unclearShown.map((m, i) => (
              <li key={i} className="rounded-xl bg-paper px-3 py-2 text-[15px] leading-relaxed">
                <span className="text-ink-soft">읽으려던 단어 </span>
                <span lang="en" className="font-semibold">
                  <WordText text={m.target} />
                </span>
                <span className="block text-ink-soft">
                  들린 문장:{' '}
                  {m.heard_text.trim() ? (
                    <span lang="en" className="text-ink"><WordText text={m.heard_text} /></span>
                  ) : (
                    <span className="text-ink">(아무것도 받아쓰지 못했어요)</span>
                  )}
                </span>
              </li>
            ))}
            {unclearAll.length > unclearShown.length && <li className="text-sm text-ink-soft">그 밖에 {unclearAll.length - unclearShown.length}개가 더 있어요.</li>}
          </ul>
        </div>
      )}
      {c.tip && (
        <div className="mt-4 border-t border-line pt-3">
          <h4 className="text-sm font-semibold text-ink-soft">고치는 방법</h4>
          <p className="mt-1 text-[15px] leading-relaxed">{c.tip}</p>
        </div>
      )}
    </article>
  );
}

function Results({ result, onRetake, retaking }: { result: PronResult; onRetake: () => void; retaking: boolean }) {
  const measured = result.contrasts.filter((c) => c.total > 0);
  const trouble = measured.filter((c) => c.as_other + c.unclear > 0).sort((a, b) => severity(b) - severity(a));
  const clean = measured.filter((c) => c.as_other + c.unclear === 0);
  return (
    <Screen wide>
      <TopBar title="발음 진단 결과" onBack={() => go('home')} />
      <p className="max-w-[640px] leading-relaxed text-ink-soft">
        {result.date}에 읽은 문장을 받아쓰기가 들은 그대로 비교한 결과예요. 점수가 아니라 내 발음 습관이에요. 숫자는 다르게 들린 문장 수 / 해당 소리가 들어간 문장 수예요.
      </p>

      {trouble.length > 0 ? (
        <div className={`mt-6 grid gap-4 lg:items-start ${trouble.length > 1 ? 'lg:grid-cols-2' : 'lg:max-w-[520px]'}`}>
          {trouble.map((c) => (
            <ContrastCard key={c.contrast} c={c} />
          ))}
        </div>
      ) : (
        <p className="mt-6 rounded-2xl border border-line bg-surface p-5">이번에는 다르게 들린 소리가 없었어요.</p>
      )}

      {clean.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 font-semibold">잘 들린 소리</h2>
          <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
            {clean.map((c) => (
              <li key={c.contrast} className="flex min-h-12 items-center gap-3 px-4 py-3">
                <Check size={18} className="shrink-0 text-call" aria-hidden />
                <span className="flex-1 font-semibold">
                  <WordText text={c.label} />
                </span>
                <span className="text-sm tabular-nums text-ink-soft">0/{c.total}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-8 flex flex-col gap-3 lg:flex-row">
        <PrimaryButton onClick={onRetake} disabled={retaking}>
          <RotateCcw size={20} aria-hidden />
          다시 진단하기
        </PrimaryButton>
        <QuietButton onClick={() => go('home')}>홈으로</QuietButton>
      </div>
    </Screen>
  );
}

export function Pron() {
  const [test, setTest] = useState<PronTest | null>(null);
  const [latest, setLatest] = useState<PronResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [phase, setPhase] = useState<'intro' | 'test' | 'results'>('intro');
  const [result, setResult] = useState<PronResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);

  const load = useCallback(() => {
    const controller = new AbortController();
    setLoadError(null);
    Promise.all([getPronTest(controller.signal), getPronLatest(controller.signal).catch(() => null)]).then(
      ([t, l]) => {
        setTest(t);
        setLatest(l);
      },
      (e: unknown) => {
        if (!controller.signal.aborted) setLoadError(e instanceof Error ? e.message : '진단 문장을 불러오지 못했어요.');
      },
    );
    return () => controller.abort();
  }, []);

  useEffect(() => load(), [load]);

  const begin = async () => {
    setBusy(true);
    try {
      setTest(await getPronTest());
    } catch {
      // 새 문장을 못 받으면 이미 받은 문장으로 진행한다.
    }
    setBusy(false);
    setRound((r) => r + 1);
    setPhase('test');
  };

  if (phase === 'test' && test) {
    return (
      <Session
        key={round}
        items={test.items}
        onExit={() => setPhase('intro')}
        onDone={(r) => {
          setResult(r);
          setLatest(r);
          setPhase('results');
        }}
      />
    );
  }

  if (phase === 'results' && result) {
    return <Results result={result} onRetake={() => void begin()} retaking={busy} />;
  }

  return (
    <Screen>
      <TopBar title="발음 진단" onBack={() => go('home')} />
      <p className="text-lg font-semibold leading-relaxed">내 발음 습관이 어떤지 먼저 재 봐요.</p>
      <p className="mt-2 leading-relaxed text-ink-soft">
        Ms. Park이 문장을 하나씩 보여 줄게요. 소리 내어 읽으면 프로그램이 들린 그대로 받아써요. 고쳐 주지 않아요. can과 can’t처럼 비슷한 소리가 어떻게 들리는지 알아보는 거예요.
      </p>

      <ul className="mt-6 divide-y divide-line overflow-hidden rounded-2xl border border-line bg-surface">
        <li className="flex items-start gap-3 px-4 py-4">
          <Clock size={20} className="mt-0.5 shrink-0 text-ink-soft" aria-hidden />
          <span>문장 {test ? `${test.items.length}개` : '여러 개'}, 5분쯤 걸려요.</span>
        </li>
        <li className="flex items-start gap-3 px-4 py-4">
          <Mic size={20} className="mt-0.5 shrink-0 text-ink-soft" aria-hidden />
          <span>조용한 곳에서 해 주세요. 처음 누를 때 마이크 사용을 허용해야 해요.</span>
        </li>
        <li className="flex items-start gap-3 px-4 py-4">
          <AudioLines size={20} className="mt-0.5 shrink-0 text-ink-soft" aria-hidden />
          <span>평소 말하듯 자연스럽게 읽어요. 일부러 또박또박 읽으면 평소 습관이 안 보여요.</span>
        </li>
      </ul>

      {latest && (
        <section className="mt-4 flex items-center gap-3 rounded-2xl border border-line bg-surface p-4">
          <p className="flex-1 text-[15px]">
            지난 진단: <span className="font-semibold">{latest.date}</span>
          </p>
          <div className="shrink-0">
            <QuietButton
              onClick={() => {
                setResult(latest);
                setPhase('results');
              }}
            >
              지난 결과 보기
            </QuietButton>
          </div>
        </section>
      )}

      {loadError && (
        <div role="alert" className="mt-4">
          <p className="text-end-press">{loadError}</p>
          <div className="mt-3">
            <QuietButton onClick={load}>다시 불러오기</QuietButton>
          </div>
        </div>
      )}

      <div className="mt-auto pt-8">
        <PrimaryButton onClick={() => void begin()} disabled={!test || busy}>
          <Mic size={22} aria-hidden />
          {latest ? '다시 진단하기' : '진단 시작하기'}
        </PrimaryButton>
      </div>
    </Screen>
  );
}
