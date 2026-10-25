import { Captions, CaptionsOff, Link2, Mic, MicOff, MoonStar, Pause, Phone, PhoneOff, Play, Volume2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { BlackScreen } from '../components/BlackScreen';
import { CallMicNotice } from '../components/CallMicNotice';
import { CallReplayButton } from '../components/CallReplayButton';
import { CallThinking } from '../components/CallThinking';
import type { MemoryState } from '../components/FriendMemory';
import { ShareRow } from '../components/ShareRow';
import { SharedClipCard } from '../components/SharedClipCard';
import { TalkingPortrait } from '../components/TalkingPortrait';
import { TopicChips, type TopicChip } from '../components/TopicChips';
import { QuietButton, useWide } from '../components/ui';
import { WordText } from '../components/WordText';
import { getPartnerMemory, serverNow, type Wordbook } from '../lib/api';
import { elapsedNoticeText, elapsedSeconds, nextElapsedNotice, NOTICE_SHOW_MS, shouldOfferRedial } from '../lib/callTime';
import { useKeyboardInset } from '../lib/keyboardInset';
import { go } from '../lib/router';
import { cleanInterests, sanitizeTopic, type PracticeWord } from '../lib/instructions';
import { isPark, partnerById, PARK_ID } from '../lib/partners';
import { clipKey, linkLabel, withoutUrl } from '../lib/share';
import { BLACK_DELAY_MS, loadScreenMode, useScreenLock } from '../lib/screenLock';
import { buildInstruction, callMode, callTitle, practiceWordsFor, type CallSetup, type FinishedCall } from '../lib/setup';
import { useCall } from '../lib/useCall';

const NO_CHIP = 'none';

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

export function Call({ setup: baseSetup, brief, practiceWords, interests, wordbook = null, timeLimit, onFinished }: {
  setup: CallSetup;
  brief: string;
  practiceWords: PracticeWord[];
  interests?: string[];
  wordbook?: Wordbook | null;
  // null이면 제한 시간이 없다(친구 통화). 화면은 남은 시간 대신 지난 시간을 센다.
  timeLimit: number | null;
  onFinished: (call: FinishedCall) => void;
}) {
  const call = useCall();
  const wide = useWide();
  const partnerId = baseSetup.kind === 'teachback' ? PARK_ID : baseSetup.partner ?? PARK_ID;
  const partner = partnerById(partnerId);
  const wantsMemory = (baseSetup.kind === 'smalltalk' || baseSetup.kind === 'freetalk') && !isPark(partner);
  const [loaded, setLoaded] = useState<{ id: string; state: MemoryState }>({ id: partnerId, state: { status: 'loading' } });
  const memoryState: MemoryState = loaded.id === partnerId ? loaded.state : { status: 'loading' };
  const [chosenChip, setChosenChip] = useState({ partnerId, id: NO_CHIP });
  const chips = useMemo<TopicChip[]>(() => {
    const wantsChips = baseSetup.kind === 'smalltalk' || (baseSetup.kind === 'freetalk' && !sanitizeTopic(baseSetup.topic));
    if (!wantsChips) return [];
    const threads = wantsMemory && memoryState.status === 'ready' && memoryState.memory ? memoryState.memory.threads : [];
    const list: TopicChip[] = [
      { id: NO_CHIP, label: '그냥 시작' },
      ...threads.map((t) => ({ id: `thread:${t.text}`, label: t.ko, value: t.text })),
      ...cleanInterests(interests).map((text) => ({ id: `interest:${text}`, label: text, value: text })),
    ];
    return list.filter((c, i) => list.findIndex((o) => o.id === c.id) === i);
  }, [baseSetup, wantsMemory, memoryState, interests]);
  const chip = chips.find((c) => c.id === (chosenChip.partnerId === partnerId ? chosenChip.id : NO_CHIP)) ?? chips[0];
  const chipValue = chip?.value;
  const setup = useMemo<CallSetup>(() => {
    if (baseSetup.kind === 'teachback') return baseSetup;
    if (baseSetup.kind === 'mission') return { ...baseSetup, partner: partnerId };
    return { ...baseSetup, partner: partnerId, chip: chipValue };
  }, [baseSetup, partnerId, chipValue]);
  const idle = call.status === 'ready' || call.status === 'error';
  const showChips = idle && chips.length > 0;

  useEffect(() => {
    if (!idle || !wantsMemory) return;
    const controller = new AbortController();
    getPartnerMemory(partnerId, controller.signal).then(
      (memory) => setLoaded({ id: partnerId, state: { status: 'ready', memory } }),
      (e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setLoaded({ id: partnerId, state: { status: 'failed' } });
      },
    );
    return () => controller.abort();
  }, [idle, wantsMemory, partnerId]);

  const [captions, setCaptions] = useState(true);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [wantSummary, setWantSummary] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [laterKey, setLaterKey] = useState<string | null>(null);
  const noticeCount = useRef(0);
  const [now, setNow] = useState(() => Date.now());
  const captionsEnd = useRef<HTMLDivElement | null>(null);
  const reported = useRef(false);
  const pushedRef = useRef(false);
  const title = callTitle(setup);
  const { hangUp } = call;
  const live = call.status === 'live';
  const inCall = call.status === 'connecting' || live;
  const [screenMode] = useState(() => loadScreenMode());
  const screen = useScreenLock(inCall, screenMode);
  const keyboard = useKeyboardInset(inCall);
  useEffect(() => {
    if (live && screen.denied) setNotice('저전력 모드라 화면이 꺼질 수 있어요. 화면이 꺼지면 통화가 끊길 수 있어요.');
  }, [live, screen.denied]);
  const [blackOn, setBlackOn] = useState(false);
  const blackDone = useRef(false);
  // 친구 통화가 저절로 끊기면 요약으로 넘어가기 전에 다시 걸지 묻는다.
  const offerRedial = call.status === 'ended' && shouldOfferRedial(callMode(setup), call.endReason);

  // 검은 화면 모드: 연결되고 5초 뒤 한 번 덮는다. 풀고 나면 그 통화에서는 다시 덮지 않는다.
  useEffect(() => {
    if (!live) {
      setBlackOn(false);
      blackDone.current = false;
      return;
    }
    if (screenMode !== 'black') return;
    const timer = window.setTimeout(() => {
      if (blackDone.current) return;
      blackDone.current = true;
      setBlackOn(true);
    }, BLACK_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [live, screenMode]);
  const blackNow = () => {
    blackDone.current = true;
    setBlackOn(true);
  };

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
    if (call.status === 'ended' && startedAt && !reported.current && (!offerRedial || wantSummary)) {
      reported.current = true;
      const finished: FinishedCall = {
        setup,
        startedAt,
        endedAt: serverNow(),
        pausedMs: call.pausedTotal,
        result: call.result,
        endReason: call.endReason,
        practiceWords: practiceWordsFor(setup, practiceWords, wordbook).map((w) => w.lemma),
        sharedClips: call.sharedClips,
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
  }, [call.status, call.result, call.endReason, call.sharedClips, onFinished, setup, startedAt, practiceWords, wordbook, offerRedial, wantSummary]);

  useEffect(() => {
    captionsEnd.current?.scrollIntoView({ block: 'end' });
  }, [call.lines]);

  const dialing = useRef(false);
  const dial = async () => {
    if (dialing.current) return;
    dialing.current = true;
    try {
      const memory = wantsMemory && memoryState.status === 'ready' ? memoryState.memory : null;
      setStartedAt(serverNow());
      setNow(Date.now());
      setWantSummary(false);
      setLaterKey(null);
      setNotice(null);
      noticeCount.current = 0;
      await call.start(
        buildInstruction(setup, brief, practiceWordsFor(setup, practiceWords, wordbook), cleanInterests(interests), memory, wordbook),
        callMode(setup),
        partner.voice,
        wantsMemory ? partnerId : undefined,
        {
          ...(setup.kind === 'teachback' ? { lesson_date: setup.lessonDate } : {}),
          practice_words: practiceWordsFor(setup, practiceWords, wordbook).map((w) => w.lemma),
        },
      );
    } finally {
      dialing.current = false;
    }
  };

  // 남은 시간 = 제한 - (지금 - 시작 - 멈춰 있던 시간 합계). 일시정지 중에는 '지금'을 멈춘 시각으로 고정한다.
  const clockNow = call.pausedAt ?? now;
  const elapsed = elapsedSeconds(now, call.liveAt, call.pausedTotal, call.pausedAt);
  const remaining = timeLimit === null ? null : call.liveAt ? Math.min(timeLimit, timeLimit - (clockNow - call.liveAt - call.pausedTotal) / 1000) : timeLimit;

  // 제한 시간이 없는 통화: 10분마다 조용한 알림을 한 번 띄우고 몇 초 뒤 거둔다(화면을 막지 않는다).
  useEffect(() => {
    if (timeLimit !== null || !live) return;
    const due = nextElapsedNotice(elapsed, noticeCount.current);
    if (!due) return;
    noticeCount.current = due.count;
    setNotice(elapsedNoticeText(due.minutes));
  }, [timeLimit, live, elapsed]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), NOTICE_SHOW_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);
  const latestClip = call.sharedClips[call.sharedClips.length - 1];
  const clipCard = live && latestClip && clipKey(latestClip) !== laterKey ? latestClip : null;
  const canShare = live && setup.kind !== 'teachback';
  const resumeCall = () => {
    call.resume();
    setNow(Date.now());
  };
  const showThinking = live && call.thinking && !call.paused && !call.botSpeaking && !call.reconnecting;
  const thinkingSubject = setup.kind === 'teachback' ? '학생이' : isPark(partner) ? 'Ms. Park이' : `${partner.name}님이`;
  const speakingLabel = setup.kind === 'teachback' ? '학생이 말하는 중' : isPark(partner) ? 'Ms. Park이 말하는 중' : `${partner.name}님이 말하는 중`;
  const status =
    call.status === 'ready'
      ? '준비되면 통화 버튼을 누르세요'
      : call.status === 'ended'
        ? '연결이 끝났어요'
        : call.status === 'connecting'
          ? '연결하는 중이에요'
          : call.status === 'error'
            ? call.error || '연결하지 못했어요'
            : call.reconnecting
              ? '연결이 끊겨 다시 연결하는 중…'
              : call.paused
              ? '일시정지 중이에요. 다시 시작을 누르면 이어서 해요.'
              : !call.micOn
                ? '마이크가 꺼져 있어요'
                : call.botSpeaking
                  ? speakingLabel
                  : '듣고 있어요';

  return (
    <main
      style={keyboard ? { paddingBottom: keyboard + 12 } : undefined}
      className="mx-auto flex h-dvh w-full max-w-[480px] flex-col px-5 pt-[calc(12px+env(safe-area-inset-top))] pb-[calc(20px+env(safe-area-inset-bottom))] lg:grid lg:max-w-[1120px] lg:grid-cols-[360px_minmax(0,1fr)] lg:grid-rows-[auto_minmax(0,1fr)_auto] lg:gap-x-12 lg:px-10 lg:pt-10 lg:pb-10">
      <header className="flex min-h-11 items-center justify-between gap-3 lg:col-start-1 lg:row-start-1">
        <p className="min-w-0 truncate font-semibold">{title}</p>
        {call.status === 'live' && (
          <p role="timer" className={`flex shrink-0 items-center gap-1.5 tabular-nums ${call.paused || remaining === null ? 'text-ink' : remaining < 60 ? 'font-semibold text-end-press' : 'text-ink-soft'}`}>
            <span className={remaining === null ? 'text-xs' : 'sr-only'}>{remaining === null ? '지난 시간' : '남은 시간 '}</span>
            {call.paused && <Pause size={16} aria-hidden />}
            {clock(remaining ?? elapsed)}
          </p>
        )}
      </header>

      <section className="flex flex-col items-center pt-6 text-center lg:col-start-1 lg:row-start-2 lg:self-center lg:pt-0">
        <TalkingPortrait
          size={live ? (clipCard && !wide ? 120 : 168) : showChips && !wide ? 140 : 200}
          level={call.botLevel}
          active={call.botSpeaking}
          src={partner.portrait}
          alt={partner.name}
          mouth={isPark(partner)}
        />
        <h1 className="mt-4 text-2xl font-bold">{partner.name}</h1>
        <p className={`mt-1 min-h-6 ${call.status === 'error' ? 'text-end-press' : 'text-ink-soft'}`} role="status">
          {showThinking ? <CallThinking name={thinkingSubject} /> : status}
        </p>
        {live && !call.paused && call.micNotice !== 'ok' && <CallMicNotice state={call.micNotice} />}
        {live && call.canReplay && <CallReplayButton ready={call.replayReady} replaying={call.replaying} onClick={() => void call.replayLast()} />}
        {live && notice && (
          <p role="status" className="mt-3 rounded-full bg-paper px-4 py-2 text-sm text-ink-soft">
            {notice}
          </p>
        )}
        {inCall && screenMode !== 'system' && !screen.supported && <p className="mt-2 text-sm text-ink-soft">이 브라우저는 화면 켜두기를 지원하지 않아요</p>}
        {live && screen.resumed && (
          <div role="alert" className="mt-3 flex w-full max-w-xs items-center gap-1 rounded-2xl border border-line bg-surface py-2 pl-4 text-left text-sm">
            <p className="flex-1">화면이 꺼져 있는 동안 마이크가 멈췄을 수 있어요. 말이 안 들리면 음소거를 껐다 켜 보세요.</p>
            <button type="button" onClick={screen.dismissResumed} aria-label="안내 닫기" className="grid size-11 shrink-0 place-items-center rounded-full text-ink-soft hover:bg-line/60">
              <X size={18} aria-hidden />
            </button>
          </div>
        )}
        {call.status === 'live' && call.audioBlocked && (
          <div className="mt-3 w-full max-w-xs">
            <QuietButton onClick={call.resumeAudio}>
              <Volume2 size={20} aria-hidden />
              소리가 안 나오면 눌러 주세요
            </QuietButton>
          </div>
        )}
      </section>

      {showChips && (
        <section className="mt-4 min-h-0 flex-1 overflow-y-auto lg:col-start-2 lg:row-span-3 lg:row-start-1 lg:mt-0 lg:max-h-full lg:flex-none lg:self-center">
          <TopicChips chips={chips} value={chip?.id ?? NO_CHIP} onChange={(id) => setChosenChip({ partnerId, id })} />
        </section>
      )}

      {!showChips && (
      <section
        className="mt-4 min-h-0 flex-1 overflow-y-auto lg:col-start-2 lg:row-span-3 lg:row-start-1 lg:mt-0 lg:flex-none lg:rounded-2xl lg:border lg:border-line lg:bg-surface lg:p-8"
        aria-label="실시간 자막"
        aria-live="polite"
      >
        {(!captions || call.lines.length === 0) && (
          <p className="hidden text-ink-soft lg:block">
            {!captions ? '자막이 꺼져 있어요.' : call.status === 'live' ? '대화가 시작되면 자막이 여기에 나와요.' : '통화를 시작하면 대화가 여기에 나와요.'}
          </p>
        )}
        {captions && call.lines.length > 0 && (
          <div className="space-y-3 rounded-2xl bg-surface p-4 lg:space-y-4 lg:rounded-none lg:bg-transparent lg:p-0 lg:text-lg lg:leading-relaxed">
            {call.lines.map((line) => {
              const body = line.share ? withoutUrl(line.text) : line.text;
              return (
                <p key={line.id} className={line.who === 'me' ? 'text-right text-ink' : 'text-ink'}>
                  <span className="mr-1.5 text-xs font-semibold text-ink-soft">{line.who === 'me' ? '나' : partner.name}</span>
                  {body && <WordText text={body} />}
                  {line.share && (
                    <a
                      href={line.share.url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => {
                        if (inCall && !window.confirm('통화 중에 링크를 열면 상대 목소리가 끊길 수 있어요. 지금 열까요?')) e.preventDefault();
                      }}
                      className={`mt-1 ml-auto flex w-fit max-w-full items-center gap-1.5 rounded-full border border-line bg-paper px-3 py-1.5 text-sm ${line.share.failed ? 'text-end-press' : 'text-ink-soft'}`}
                    >
                      <Link2 size={14} aria-hidden className="shrink-0" />
                      <span className="truncate">{linkLabel(line.share.url, line.share.title)}</span>
                    </a>
                  )}
                </p>
              );
            })}
            <div ref={captionsEnd} />
          </div>
        )}
      </section>
      )}

      <footer className="pt-4 lg:col-start-1 lg:row-start-3">
        {offerRedial ? (
          <div className="flex flex-col items-center gap-4">
            <p role="alert" className="text-center text-lg font-semibold">
              연결이 끝났어요. 다시 걸까요?
            </p>
            <RoundButton label="다시 걸기" tone="call" onClick={() => void dial()}>
              <Phone size={30} aria-hidden />
            </RoundButton>
            <QuietButton onClick={() => setWantSummary(true)}>통화 정리 보기</QuietButton>
          </div>
        ) : call.status === 'ready' || call.status === 'error' ? (
          <div className="flex flex-col items-center gap-4">
            <RoundButton label={call.status === 'error' ? '다시 걸기' : '통화'} tone="call" onClick={() => void dial()}>
              <Phone size={30} aria-hidden />
            </RoundButton>
            <QuietButton onClick={() => go('home')}>홈으로</QuietButton>
          </div>
        ) : (
          <div className="space-y-3">
            {clipCard && (
              <SharedClipCard
                key={clipKey(clipCard)}
                clip={clipCard}
                from={partner.name}
                onLater={() => {
                  setLaterKey(clipKey(clipCard));
                  setNotice('요약 화면에 담아 뒀어요');
                }}
              />
            )}
            {canShare && <ShareRow onSend={call.share} disabled={call.paused} />}
          <div className="flex items-end justify-center gap-3">
            <RoundButton label={captions ? '자막 끄기' : '자막 켜기'} tone={captions ? 'on' : 'plain'} onClick={() => setCaptions((v) => !v)}>
              {captions ? <Captions size={24} aria-hidden /> : <CaptionsOff size={24} aria-hidden />}
            </RoundButton>
            {live && (
              <RoundButton label="화면 끄기" onClick={blackNow}>
                <MoonStar size={24} aria-hidden />
              </RoundButton>
            )}
            {live && (
              <RoundButton label={call.paused ? '다시 시작' : '일시정지'} tone={call.paused ? 'on' : 'plain'} onClick={call.paused ? resumeCall : call.pause}>
                {call.paused ? <Play size={24} aria-hidden /> : <Pause size={24} aria-hidden />}
              </RoundButton>
            )}
            <RoundButton label="끊기" tone="end" onClick={call.hangUp}>
              <PhoneOff size={30} aria-hidden />
            </RoundButton>
            <RoundButton label={call.micOn ? '음소거' : '음소거 해제'} tone={call.micOn ? 'plain' : 'on'} onClick={call.paused ? () => undefined : call.toggleMic}>
              {call.micOn ? <Mic size={24} aria-hidden /> : <MicOff size={24} aria-hidden />}
            </RoundButton>
          </div>
          </div>
        )}
      </footer>
      {live && blackOn && <BlackScreen onRelease={() => setBlackOn(false)} />}
    </main>
  );
}
