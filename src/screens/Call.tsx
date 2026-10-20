import { Captions, CaptionsOff, Mic, MicOff, Phone, PhoneOff } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { TalkingPortrait } from '../components/TalkingPortrait';
import { QuietButton } from '../components/ui';
import { serverNow } from '../lib/api';
import { go } from '../lib/router';
import type { PracticeWord } from '../lib/instructions';
import { buildInstruction, callMode, callTitle, practiceWordsFor, type CallSetup, type FinishedCall } from '../lib/setup';
import { useCall } from '../lib/useCall';

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function RoundButton({ label, onClick, tone = 'plain', children }: {
  label: string;
  onClick: () => void;
  tone?: 'plain' | 'on' | 'end' | 'call';
  children: ReactNode;
}) {
  const tones = {
    plain: 'bg-surface text-ink border border-line',
    on: 'bg-ink text-white',
    end: 'bg-end text-white active:bg-end-press',
    call: 'bg-call text-white active:bg-call-press',
  };
  const size = tone === 'end' || tone === 'call' ? 'size-[72px]' : 'size-14';
  return (
    <div className="flex flex-col items-center gap-1.5">
      <button type="button" onClick={onClick} aria-label={label} className={`grid ${size} place-items-center rounded-full ${tones[tone]}`}>
        {children}
      </button>
      <span className="text-xs text-ink-soft" aria-hidden>
        {label}
      </span>
    </div>
  );
}

export function Call({ setup, brief, practiceWords, timeLimit, onFinished }: {
  setup: CallSetup;
  brief: string;
  practiceWords: PracticeWord[];
  timeLimit: number;
  onFinished: (call: FinishedCall) => void;
}) {
  const call = useCall();
  const [captions, setCaptions] = useState(true);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const captionsEnd = useRef<HTMLDivElement | null>(null);
  const reported = useRef(false);
  const pushedRef = useRef(false);
  const title = callTitle(setup);
  const { hangUp } = call;

  // 연결 중·통화 중에는 같은 #/call 항목을 하나 더 쌓아 두고, 뒤로 가기(popstate)를 끊기로 처리한다.
  useEffect(() => {
    if (call.status !== 'connecting' && call.status !== 'live') return;
    if (!pushedRef.current) {
      window.history.pushState(window.history.state, '', window.location.href);
      pushedRef.current = true;
    }
    const onPop = () => {
      pushedRef.current = false; // 쌓아 둔 항목은 뒤로 가기로 이미 소비됐다.
      hangUp();
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [call.status, hangUp]);

  // 연결 실패로 통화 화면이 다시 준비 상태가 되면 쌓아 둔 항목을 걷어 낸다.
  useEffect(() => {
    if ((call.status === 'error' || call.status === 'ready') && pushedRef.current) {
      pushedRef.current = false;
      window.history.back();
    }
  }, [call.status]);

  useEffect(() => {
    if (call.status !== 'live') return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [call.status]);

  useEffect(() => {
    if (call.status === 'ended' && startedAt && !reported.current) {
      reported.current = true;
      const finished: FinishedCall = {
        setup,
        startedAt,
        endedAt: serverNow(),
        result: call.result,
        endReason: call.endReason,
        practiceWords: practiceWordsFor(setup, practiceWords).map((w) => w.lemma),
      };
      if (pushedRef.current) {
        // 끊기 버튼·미션 완료 등으로 끝난 경우: 쌓아 둔 항목을 먼저 걷어 낸 뒤 요약으로 이동한다.
        // popstate가 오지 않는 브라우저에서도 요약을 잃지 않게 0.8초 뒤에는 그냥 넘어간다(한 번만).
        pushedRef.current = false;
        let sent = false;
        const finish = () => {
          if (sent) return;
          sent = true;
          window.removeEventListener('popstate', finish);
          window.clearTimeout(fallback);
          onFinished(finished);
        };
        const fallback = window.setTimeout(finish, 800);
        window.addEventListener('popstate', finish);
        window.history.back();
      } else {
        onFinished(finished);
      }
    }
  }, [call.status, call.result, call.endReason, onFinished, setup, startedAt, practiceWords]);

  useEffect(() => {
    captionsEnd.current?.scrollIntoView({ block: 'end' });
  }, [call.lines]);

  const dial = () => {
    setStartedAt(serverNow());
    setNow(Date.now());
    void call.start(buildInstruction(setup, brief, practiceWordsFor(setup, practiceWords)), callMode(setup));
  };

  const remaining = call.liveAt ? Math.min(timeLimit, timeLimit - (now - call.liveAt) / 1000) : timeLimit;
  const status =
    call.status === 'ready'
      ? '준비되면 통화 버튼을 누르세요'
      : call.status === 'connecting'
        ? '연결하는 중이에요'
        : call.status === 'error'
          ? call.error || '연결하지 못했어요'
          : !call.micOn
            ? '마이크가 꺼져 있어요'
            : call.botSpeaking
              ? setup.kind === 'teachback' ? '학생이 말하는 중' : 'Ms. Park이 말하는 중'
              : '듣고 있어요';

  return (
    <main className="mx-auto flex h-dvh w-full max-w-[480px] flex-col px-5 pt-[calc(12px+env(safe-area-inset-top))] pb-[calc(20px+env(safe-area-inset-bottom))]">
      <header className="flex min-h-11 items-center justify-between gap-3">
        <p className="min-w-0 truncate font-semibold">{title}</p>
        {call.status === 'live' && (
          <p role="timer" className={`shrink-0 tabular-nums ${remaining < 60 ? 'font-semibold text-end-press' : 'text-ink-soft'}`}>
            <span className="sr-only">남은 시간 </span>
            {clock(remaining)}
          </p>
        )}
      </header>

      <section className="flex flex-col items-center pt-6 text-center">
        <TalkingPortrait size={call.status === 'live' ? 168 : 200} level={call.botLevel} active={call.botSpeaking} />
        <h1 className="mt-4 text-2xl font-bold">Ms. Park</h1>
        <p className={`mt-1 min-h-6 ${call.status === 'error' ? 'text-end-press' : 'text-ink-soft'}`} role="status">
          {status}
        </p>
      </section>

      <section className="mt-4 min-h-0 flex-1 overflow-y-auto" aria-label="실시간 자막" aria-live="polite">
        {captions && call.lines.length > 0 && (
          <div className="space-y-3 rounded-2xl bg-surface p-4">
            {call.lines.map((line) => (
              <p key={line.id} className={line.who === 'me' ? 'text-right text-ink' : 'text-ink'}>
                <span className="mr-1.5 text-xs font-semibold text-ink-soft">{line.who === 'me' ? '나' : 'Ms. Park'}</span>
                {line.text}
              </p>
            ))}
            <div ref={captionsEnd} />
          </div>
        )}
      </section>

      <footer className="pt-4">
        {call.status === 'ready' || call.status === 'error' ? (
          <div className="flex flex-col items-center gap-4">
            <RoundButton label={call.status === 'error' ? '다시 걸기' : '통화'} tone="call" onClick={dial}>
              <Phone size={30} aria-hidden />
            </RoundButton>
            <QuietButton onClick={() => go('home')}>홈으로</QuietButton>
          </div>
        ) : (
          <div className="flex items-end justify-center gap-8">
            <RoundButton label={captions ? '자막 끄기' : '자막 켜기'} tone={captions ? 'on' : 'plain'} onClick={() => setCaptions((v) => !v)}>
              {captions ? <Captions size={24} aria-hidden /> : <CaptionsOff size={24} aria-hidden />}
            </RoundButton>
            <RoundButton label="끊기" tone="end" onClick={call.hangUp}>
              <PhoneOff size={30} aria-hidden />
            </RoundButton>
            <RoundButton label={call.micOn ? '음소거' : '음소거 해제'} tone={call.micOn ? 'plain' : 'on'} onClick={call.toggleMic}>
              {call.micOn ? <Mic size={24} aria-hidden /> : <MicOff size={24} aria-hidden />}
            </RoundButton>
          </div>
        )}
      </footer>
    </main>
  );
}
