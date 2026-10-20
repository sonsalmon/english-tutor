import { Check, Eye, EyeOff, Mic, Play, RotateCcw, Square, Volume2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { QuietButton, Screen, TopBar } from '../components/ui';
import { TalkingPortrait } from '../components/TalkingPortrait';
import { WordText } from '../components/WordText';
import { isPark, partnerMeta } from '../lib/partners';
import { MicError, startRecorder, transcribePron, type Recorder } from '../lib/pron';
import {
  diffWords,
  fetchTts,
  isExact,
  loadReplay,
  partnerForVoice,
  words,
  type DiffOp,
  type LearnerStep,
  type ReplayData,
} from '../lib/replay';
import { go } from '../lib/router';

const METER_BARS = 14;
const MIN_SECONDS = 0.5;
const MIN_PEAK = 0.01;

type TurnResult = { heard: string; exact: boolean; skipped: boolean };

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

function Chip({ children }: { children: ReactNode }) {
  return <span className="inline-block rounded-full bg-paper px-2.5 py-1 text-xs font-semibold text-ink">{children}</span>;
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

// 밑줄 + 형광펜: 못 들은 말. 취소선 + 빨강: 더 들린 말. 색만으로 구분하지 않도록 모양과 보이지 않는 글자도 붙인다.
function DiffLine({ ops }: { ops: DiffOp[] }) {
  return (
    <p data-replay-diff lang="en" className="text-[24px] leading-snug font-bold lg:text-[32px]">
      {ops.map((op, i) => (
        <span key={i}>
          {i > 0 && ' '}
          {op.kind === 'same' ? (
            op.word
          ) : op.kind === 'missing' ? (
            <span data-diff="missing" className="mark underline decoration-2 underline-offset-4">
              {op.word}
              <span className="sr-only"> (빠짐)</span>
            </span>
          ) : (
            <span data-diff="extra" className="text-end-press line-through decoration-2">
              {op.word}
              <span className="sr-only"> (더 들림)</span>
            </span>
          )}
        </span>
      ))}
    </p>
  );
}

function DiffSummary({ ops }: { ops: DiffOp[] }) {
  const missing = ops.filter((o) => o.kind === 'missing').map((o) => o.word);
  const extra = ops.filter((o) => o.kind === 'extra').map((o) => o.word);
  return (
    <div className="mt-3 space-y-1 text-[15px] leading-relaxed" data-replay-summary>
      <p>
        <span className="font-semibold">못 들은 말 (밑줄)</span>{' '}
        <span lang="en">{missing.length ? missing.join(', ') : '없음'}</span>
      </p>
      <p>
        <span className="font-semibold">더 들린 말 (취소선)</span>{' '}
        <span lang="en">{extra.length ? extra.join(', ') : '없음'}</span>
      </p>
    </div>
  );
}

function PartnerView({
  text,
  getAudio,
  onSpeaking,
  onNext,
  nextLabel,
  speaker,
}: {
  text: string;
  getAudio: (text: string) => Promise<Blob>;
  onSpeaking: (speaking: boolean) => void;
  onNext: () => void;
  nextLabel: string;
  speaker: string;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [status, setStatus] = useState<'loading' | 'playing' | 'ended' | 'blocked' | 'error'>('loading');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const el = audio.current;
    let cancelled = false;
    let url = '';
    setStatus('loading');
    setError('');
    getAudio(text).then(
      async (blob) => {
        if (cancelled || !el) return;
        url = URL.createObjectURL(blob);
        el.src = url;
        try {
          await el.play();
        } catch (e) {
          if (cancelled) return;
          if (e instanceof DOMException && e.name === 'NotAllowedError') setStatus('blocked');
          else if (!(e instanceof DOMException && e.name === 'AbortError')) {
            setStatus('error');
            setError('소리를 재생하지 못했어요.');
          }
        }
      },
      (e: unknown) => {
        if (cancelled) return;
        setStatus('error');
        setError(e instanceof Error ? e.message : '목소리를 만들지 못했어요.');
      },
    );
    return () => {
      cancelled = true;
      el?.pause();
      if (url) URL.revokeObjectURL(url);
      onSpeaking(false);
    };
  }, [text, getAudio, attempt, onSpeaking]);

  const press = async () => {
    const el = audio.current;
    if (status === 'error') {
      setAttempt((a) => a + 1);
      return;
    }
    if (!el || !el.src) return;
    el.currentTime = 0;
    try {
      await el.play();
    } catch {
      setStatus('error');
      setError('소리를 재생하지 못했어요.');
    }
  };

  const message =
    status === 'loading'
      ? '목소리를 불러오는 중이에요.'
      : status === 'playing'
        ? '듣는 중이에요.'
        : status === 'ended'
          ? '다 들었어요. 다시 들으려면 버튼을 눌러요.'
          : status === 'blocked'
            ? '브라우저가 자동 재생을 막았어요. 버튼을 눌러서 들어요.'
            : error;

  return (
    <>
      <section className="mt-6 rounded-2xl border border-line bg-surface p-6 lg:p-8">
        <Chip>{speaker}의 말</Chip>
        <p data-replay-partner-text lang="en" className="mt-4 text-[26px] leading-snug font-bold lg:text-[34px]">
          <WordText text={text} />
        </p>
        <audio
          ref={audio}
          data-replay-audio
          preload="auto"
          className="hidden"
          onPlaying={() => {
            setStatus('playing');
            onSpeaking(true);
          }}
          onEnded={() => {
            setStatus('ended');
            onSpeaking(false);
          }}
        />
      </section>
      <section className="mt-6 flex flex-col gap-3" aria-live="polite">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <button
            type="button"
            data-replay-play
            onClick={() => void press()}
            disabled={status === 'loading'}
            className="flex min-h-12 w-full items-center justify-center gap-2 rounded-full border border-line bg-surface px-6 font-semibold text-ink hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto lg:min-w-48"
          >
            {status === 'blocked' ? <Play size={20} aria-hidden /> : <Volume2 size={20} aria-hidden />}
            {status === 'blocked' ? '눌러서 듣기' : status === 'error' ? '다시 시도' : '다시 듣기'}
          </button>
          <p data-replay-audio-status role={status === 'error' ? 'alert' : undefined} className={`text-[15px] ${status === 'error' ? 'text-end-press' : 'text-ink-soft'}`}>
            {message}
          </p>
        </div>
        <PrimaryButton onClick={onNext}>{nextLabel}</PrimaryButton>
      </section>
    </>
  );
}

function LearnerView({ step, onDone }: { step: LearnerStep; onDone: (result: TurnResult) => void }) {
  const [phase, setPhase] = useState<'ready' | 'starting' | 'recording' | 'processing' | 'done'>('ready');
  const [level, setLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState('');
  const [hidden, setHidden] = useState(false);
  const recorder = useRef<Recorder | null>(null);
  const abort = useRef(new AbortController());
  const mounted = useRef(false);
  const stopRef = useRef<() => Promise<void>>(async () => {});

  useEffect(() => {
    mounted.current = true;
    abort.current = new AbortController();
    return () => {
      mounted.current = false;
      recorder.current?.cancel();
      recorder.current = null;
      abort.current.abort();
    };
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setPhase('starting');
    try {
      const started = await startRecorder(setLevel, () => void stopRef.current());
      if (!mounted.current) {
        started.cancel();
        return;
      }
      recorder.current = started;
      setPhase('recording');
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof MicError ? e.message : '마이크를 켜지 못했어요.');
      setPhase('ready');
    }
  }, []);

  const stop = useCallback(async () => {
    const active = recorder.current;
    if (!active) return;
    recorder.current = null;
    setLevel(0);
    setPhase('processing');
    try {
      const recording = await active.stop();
      if (recording.seconds < MIN_SECONDS) {
        setError('녹음이 너무 짧아요. 문장을 끝까지 말한 뒤에 멈춰 주세요.');
        setPhase('ready');
        return;
      }
      if (recording.peak < MIN_PEAK) {
        setError('소리가 거의 들리지 않았어요. 마이크가 켜져 있는지 확인하고 다시 말해 주세요.');
        setPhase('ready');
        return;
      }
      const text = await transcribePron(recording.blob, abort.current.signal);
      if (!mounted.current) return;
      if (!text) {
        setError('목소리를 알아듣지 못했어요. 다시 말해 주세요.');
        setPhase('ready');
        return;
      }
      setHeard(text);
      setPhase('done');
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : '받아쓰지 못했어요. 다시 말해 주세요.');
      setPhase('ready');
    }
  }, []);
  stopRef.current = stop;

  const ops = useMemo(() => (phase === 'done' ? diffWords(step.target, heard) : []), [phase, step.target, heard]);
  const exact = phase === 'done' && isExact(ops);
  const recording = phase === 'recording';
  const status =
    phase === 'recording'
      ? '녹음 중이에요. 다 말하면 버튼을 한 번 더 눌러요.'
      : phase === 'starting'
        ? '마이크를 켜는 중이에요.'
        : phase === 'processing'
          ? '들은 대로 받아쓰는 중이에요. 몇 초 걸려요.'
          : '버튼을 누르고 위 문장을 말해요.';

  return (
    <>
      <section className="mt-6 rounded-2xl border border-line bg-surface p-6 lg:p-8">
        <div className="flex items-center justify-between gap-3">
          <Chip>내 차례{step.corrected ? ' · 고친 문장' : ''}</Chip>
          {step.speakable && phase !== 'done' && (
            <button
              type="button"
              aria-pressed={hidden}
              onClick={() => setHidden((h) => !h)}
              className="flex min-h-11 items-center gap-2 rounded-full border border-line px-4 text-sm font-semibold text-ink hover:bg-paper"
            >
              {hidden ? <Eye size={18} aria-hidden /> : <EyeOff size={18} aria-hidden />}
              {hidden ? '문장 보기' : '가리고 말하기'}
            </button>
          )}
        </div>

        {phase === 'done' ? (
          <div className="mt-4">
            <DiffLine ops={ops} />
          </div>
        ) : hidden && step.speakable ? (
          <p data-replay-target-hidden aria-label="문장이 가려져 있어요" className="mt-4 flex flex-wrap gap-x-3 gap-y-2 py-1">
            {words(step.target).map((w, i) => (
              <span key={i} aria-hidden className="inline-block h-6 rounded-md bg-line lg:h-8" style={{ width: `${Math.max(1.5, w.length * 0.7)}rem` }} />
            ))}
          </p>
        ) : (
          <p data-replay-target lang="en" className="mt-4 text-[26px] leading-snug font-bold lg:text-[34px]">
            <WordText text={step.target} />
          </p>
        )}

        {step.corrected && step.why && <p className="mt-4 text-[15px] leading-relaxed">{step.why}</p>}
        <p className="mt-4 text-sm leading-relaxed text-ink-soft" data-replay-original>
          통화 때 한 말: <span lang="en">{step.original}</span>
          {!step.corrected && ' (고칠 곳이 없던 문장이에요)'}
        </p>
      </section>

      <section className="mt-6 flex flex-col items-center text-center" aria-live="polite">
        {!step.speakable ? (
          <div className="w-full">
            <p className="text-[15px] leading-relaxed text-ink-soft">한국어가 섞인 말이라 건너뛰어요.</p>
            <div className="mt-4">
              <PrimaryButton onClick={() => onDone({ heard: '', exact: false, skipped: true })}>다음</PrimaryButton>
            </div>
          </div>
        ) : phase === 'done' ? (
          <div className="w-full text-left">
            <p data-replay-heard className="text-[15px] leading-relaxed text-ink-soft">
              들린 대로: <span lang="en" className="text-ink">{heard}</span>
            </p>
            {exact ? (
              <p data-replay-verdict="exact" className="mt-3 flex items-center gap-2 text-lg font-bold">
                <Check size={22} className="text-call" aria-hidden />
                똑같이 말했어요
              </p>
            ) : (
              <>
                <p data-replay-verdict="differ" className="mt-3 text-lg font-bold">
                  조금 달라요
                </p>
                <DiffSummary ops={ops} />
              </>
            )}
            <div className="mt-6 flex flex-col gap-3 lg:flex-row">
              <PrimaryButton autoFocus onClick={() => onDone({ heard, exact, skipped: false })}>
                다음
              </PrimaryButton>
              <QuietButton
                onClick={() => {
                  setPhase('ready');
                  setHeard('');
                  setError(null);
                }}
              >
                <RotateCcw size={18} aria-hidden />
                다시 말하기
              </QuietButton>
            </div>
          </div>
        ) : (
          <>
            <button
              type="button"
              data-replay-mic
              onClick={recording ? () => void stop() : () => void start()}
              disabled={phase === 'starting' || phase === 'processing'}
              aria-label={recording ? '녹음 끝' : '녹음 시작'}
              className={`grid size-24 place-items-center rounded-full text-white shadow-[0_8px_20px_-8px_rgb(20_33_61/0.6)] disabled:cursor-not-allowed disabled:opacity-40 ${
                recording ? 'bg-end active:bg-end-press' : 'bg-ink active:bg-ink/85'
              }`}
            >
              {recording ? <Square size={30} fill="currentColor" aria-hidden /> : <Mic size={38} aria-hidden />}
            </button>
            <div className="mt-4">
              <Meter level={level} active={recording} />
            </div>
            <p data-replay-mic-status className="mt-2 text-ink-soft">
              {status}
            </p>
            {error && (
              <p role="alert" className="mt-4 w-full leading-relaxed text-end-press">
                {error}
              </p>
            )}
            <button
              type="button"
              onClick={() => onDone({ heard: '', exact: false, skipped: true })}
              disabled={phase === 'starting' || phase === 'processing' || recording}
              className="mt-4 min-h-11 rounded-full px-4 text-sm font-semibold text-ink-soft underline underline-offset-4 disabled:opacity-40"
            >
              이 문장 건너뛰기
            </button>
          </>
        )}
      </section>
    </>
  );
}

function Finished({ data, results, onRestart, onHistory }: { data: ReplayData; results: Record<number, TurnResult>; onRestart: () => void; onHistory: () => void }) {
  const learner = data.steps.flatMap((s, i) => (s.kind === 'me' && s.speakable ? [{ step: s, result: results[i] }] : []));
  const matched = learner.filter((l) => l.result?.exact).length;
  const differed = learner.filter((l) => l.result && !l.result.exact && !l.result.skipped);
  const skipped = learner.filter((l) => !l.result || l.result.skipped).length;
  return (
    <>
      <section className="mt-6 rounded-2xl border border-line bg-surface p-6 lg:p-8" data-replay-finished>
        <Chip>끝까지 했어요</Chip>
        <p className="mt-4 text-[26px] leading-snug font-bold lg:text-[34px]">
          내 차례 {learner.length - skipped}번 중 {matched}번을 똑같이 말했어요
        </p>
        {skipped > 0 && <p className="mt-2 text-ink-soft">건너뛴 문장 {skipped}개는 세지 않았어요.</p>}
      </section>

      {differed.length > 0 && (
        <section className="mt-6">
          <h2 className="mb-2 font-semibold">달랐던 문장</h2>
          <ul className="space-y-3">
            {differed.map(({ step, result }, i) => {
              const ops = diffWords(step.target, result.heard);
              return (
                <li key={i} className="rounded-2xl border border-line bg-surface p-5" data-replay-differed>
                  <DiffLine ops={ops} />
                  <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
                    들린 대로: <span lang="en" className="text-ink">{result.heard}</span>
                  </p>
                  <DiffSummary ops={ops} />
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <div className="mt-8 flex flex-col gap-3 lg:flex-row">
        <PrimaryButton onClick={onRestart}>
          <RotateCcw size={20} aria-hidden />
          처음부터 다시
        </PrimaryButton>
        <QuietButton onClick={onHistory}>기록으로</QuietButton>
      </div>
    </>
  );
}

function Run({ data }: { data: ReplayData }) {
  const partner = partnerForVoice(data.voice);
  const [round, setRound] = useState(0);
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<Record<number, TurnResult>>({});
  const [speaking, setSpeaking] = useState(false);
  const cache = useRef(new Map<string, Promise<Blob>>());
  const total = data.steps.length;
  const finished = index >= total;

  const getAudio = useCallback(
    (text: string) => {
      let promise = cache.current.get(text);
      if (!promise) {
        promise = fetchTts(text, data.voice);
        promise.catch(() => cache.current.delete(text));
        cache.current.set(text, promise);
      }
      return promise;
    },
    [data.voice],
  );

  // 다음 상대 말을 미리 만들어 둔다(서버가 캐시하므로 같은 문장은 다시 비용이 들지 않는다).
  useEffect(() => {
    const next = data.steps.findIndex((s, i) => i > index && s.kind === 'partner');
    const step = next >= 0 ? data.steps[next] : null;
    if (step?.kind === 'partner') getAudio(step.text).catch(() => {});
  }, [index, data.steps, getAudio]);

  const advance = (result?: TurnResult) => {
    if (result) setResults((r) => ({ ...r, [index]: result }));
    setIndex((i) => i + 1);
  };

  const restart = () => {
    setResults({});
    setIndex(0);
    setSpeaking(false);
    setRound((r) => r + 1);
  };

  const step = finished ? null : data.steps[index];
  const nextPartner = step?.kind === 'partner' ? (index === total - 1 ? '끝내기' : '다음') : '다음';

  return (
    <Screen>
      <TopBar title={data.mission || '통화 다시 해 보기'} onBack={() => go('history', false, data.stem)} />
      <div className="flex items-center gap-3">
        <TalkingPortrait size={56} level={0.4} active={speaking} src={partner.portrait} alt={partner.name} mouth={isPark(partner)} />
        <div className="min-w-0 flex-1">
          <p className="font-bold">{partner.name}</p>
          <p className="truncate text-sm text-ink-soft">{partnerMeta(partner)}</p>
        </div>
      </div>
      {!data.voice && <p className="mt-3 text-sm text-ink-soft">목소리가 기록되지 않은 옛 통화라 Ms. Park 목소리로 읽어요.</p>}

      <div className="mt-4 flex items-center gap-3" aria-label={`진행 ${Math.min(index + 1, total)} / ${total}`}>
        <span data-replay-progress className="min-w-14 text-sm font-semibold tabular-nums text-ink-soft">
          {Math.min(index + 1, total)} / {total}
        </span>
        <div className="h-1.5 flex-1 rounded-full bg-line" aria-hidden>
          <div className="h-full rounded-full bg-ink transition-[width] duration-300" style={{ width: `${(Math.min(index, total) / total) * 100}%` }} />
        </div>
      </div>

      {finished ? (
        <Finished data={data} results={results} onRestart={restart} onHistory={() => go('history', false, data.stem)} />
      ) : step?.kind === 'partner' ? (
        <PartnerView
          key={`${round}-${index}`}
          text={step.text}
          getAudio={getAudio}
          onSpeaking={setSpeaking}
          onNext={() => advance()}
          nextLabel={nextPartner}
          speaker={partner.name}
        />
      ) : step ? (
        <LearnerView key={`${round}-${index}`} step={step} onDone={advance} />
      ) : null}
    </Screen>
  );
}

export function Replay({ stem }: { stem: string | null }) {
  const [state, setState] = useState<{ stem: string | null; data: ReplayData | null; error: string | null }>({ stem: null, data: null, error: null });

  useEffect(() => {
    if (!stem) return;
    const controller = new AbortController();
    loadReplay(stem, controller.signal).then(
      (data) => setState({ stem, data, error: null }),
      (e: unknown) => {
        if (!controller.signal.aborted) setState({ stem, data: null, error: e instanceof Error ? e.message : '통화 기록을 불러오지 못했어요.' });
      },
    );
    return () => controller.abort();
  }, [stem]);

  const back = () => go('history', false, stem ?? undefined);
  const current = state.stem === stem ? state : { stem, data: null, error: null };

  if (!stem) {
    return (
      <Screen>
        <TopBar title="통화 다시 해 보기" onBack={() => go('history')} />
        <p className="text-ink-soft">다시 해 볼 통화를 먼저 골라 주세요.</p>
        <div className="mt-4">
          <QuietButton onClick={() => go('history')}>통화 기록으로</QuietButton>
        </div>
      </Screen>
    );
  }
  if (current.error) {
    return (
      <Screen>
        <TopBar title="통화 다시 해 보기" onBack={back} />
        <p role="alert" className="text-end-press">{current.error}</p>
        <div className="mt-4">
          <QuietButton onClick={back}>기록으로</QuietButton>
        </div>
      </Screen>
    );
  }
  if (!current.data) {
    return (
      <Screen>
        <TopBar title="통화 다시 해 보기" onBack={back} />
        <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
      </Screen>
    );
  }
  if (current.data.steps.length === 0) {
    return (
      <Screen>
        <TopBar title="통화 다시 해 보기" onBack={back} />
        <p className="text-ink-soft">이 통화에는 다시 해 볼 대화가 없어요.</p>
        <div className="mt-4">
          <QuietButton onClick={back}>기록으로</QuietButton>
        </div>
      </Screen>
    );
  }
  return <Run key={current.data.stem} data={current.data} />;
}
