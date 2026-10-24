import { PipecatClient } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';
import { useCallback, useEffect, useRef, useState } from 'react';
import { EMPTY_STATS, readStats, telemetryPayload, type StatsSample } from './callStats';
import { friendlyError } from './errors';
import { LatencyMeter, clearPendingLatency, stashLatency } from './latency';
import {
  ATTEMPT_TIMEOUT_MS,
  TELEMETRY_EVERY_MS,
  judgeHealth,
  newHealth,
  redialDelayMs,
  resumeTurns,
  shouldRedial,
  type DeadReason,
  type Health,
} from './redial';
import { clipKey, firstUrl, parseSharedClip, parseShareAck, SHARE_MAX, type SharedClip } from './share';
import { cleanLearnerText } from './transcript';

// 통화가 끝난 뒤 서버가 스스로 정리를 걸 때 쓰는 입력. 통화를 걸 때 서버에 미리 알려 둔다.
export type SummaryInput = { lesson_date?: string; practice_words?: string[] };
export type CallMode = 'mission' | 'freetalk' | 'teachback' | 'smalltalk';
export type CallStatus = 'ready' | 'connecting' | 'live' | 'ended' | 'error';
export type Speaker = 'me' | 'park';
export type SharedLink = { url: string; title?: string; failed?: boolean };
export type CaptionLine = { id: number; who: Speaker; text: string; share?: SharedLink; shareId?: string };
export type MissionResult = { score: number; feedback_pointers: string[] };
export type EndReason = 'hangup' | 'mission_complete' | 'time_limit' | 'pause_limit' | 'dropped';

const MISSION_END_DELAY_MS = 3500;

// Gemini 받아쓰기가 잡음을 `{}`로 내보낼 때가 있다(서버 call_bot.NOISE_MARK_RE와 같은 규칙).
const NOISE_MARK = /\{\s*\}/g;

function joinChunk(prev: string, chunk: string): string {
  return `${prev} ${chunk.replace(NOISE_MARK, ' ')}`.replace(/\s+/g, ' ').trim();
}

// 다시 걸 때 같은 통화를 만들려고 처음 건 인자를 그대로 들고 있는다.
type DialParams = { systemInstruction: string; mode: CallMode; voice: string; partner?: string; summaryInput?: SummaryInput };

// SmallWebRTCTransport는 PC와 데이터 채널을 공개하지 않는다. 품질 수집과 끊김 판정에만 읽는다.
type TransportInternals = { pc?: RTCPeerConnection | null; dc?: RTCDataChannel | null };

function micState(track: MediaStreamTrack | undefined): string {
  if (!track) return 'none';
  if (track.readyState === 'ended') return 'ended';
  if (track.muted) return 'muted';
  return track.enabled ? 'live' : 'off';
}

export function useCall() {
  const [status, setStatus] = useState<CallStatus>('ready');
  const [lines, setLines] = useState<CaptionLine[]>([]);
  const linesRef = useRef<CaptionLine[]>([]);
  linesRef.current = lines;
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [botLevel, setBotLevel] = useState(0);
  const [userLevel, setUserLevel] = useState(0);
  const [micOn, setMicOn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MissionResult | null>(null);
  const [endReason, setEndReason] = useState<EndReason | null>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [sharedClips, setSharedClips] = useState<SharedClip[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const shareCount = useRef(0);
  // 일시정지: 멈춘 시각(null이면 진행 중)과 지금까지 멈춰 있던 시간 합계(ms). 남은 시간 계산에 쓴다.
  const [pausedAt, setPausedAt] = useState<number | null>(null);
  const [pausedTotal, setPausedTotal] = useState(0);
  const pausedAtRef = useRef<number | null>(null);
  const micBeforePauseRef = useRef(true);

  const clientRef = useRef<PipecatClient | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const reasonRef = useRef<EndReason | null>(null);
  const liveRef = useRef(false);
  const meterRef = useRef<LatencyMeter | null>(null);
  const [liveAt, setLiveAt] = useState<number | null>(null);
  const lineId = useRef(0);

  // 자동 다시 걸기 상태. sessionRef는 연결(PipecatClient)마다 올라가고, 낡은 연결에서 늦게 온 콜백을 걸러 낸다.
  const sessionRef = useRef(0);
  const everLiveRef = useRef(false);
  const lastParamsRef = useRef<DialParams | null>(null);
  const redialTimerRef = useRef<number | null>(null);
  const attemptTimerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const redialsRef = useRef(0);
  const reconnectingRef = useRef(false);
  const healthRef = useRef<Health | null>(null);
  const micOnRef = useRef(true);
  const newLineRef = useRef(false);
  const liveStartRef = useRef<number | null>(null);
  const connectRef = useRef<(params: DialParams, redial: boolean) => Promise<void>>(() => Promise.resolve());
  const lostRef = useRef<() => void>(() => undefined);
  const recoverMicRef = useRef<() => void>(() => undefined);

  const addChunk = useCallback((who: Speaker, chunk: string) => {
    if (!chunk || !chunk.replace(NOISE_MARK, '').trim()) return;
    const text = who === 'me' ? cleanLearnerText(chunk) : chunk;
    // 다시 연결된 뒤 첫 말은 끊기기 전 말풍선에 이어 붙이지 않고 새 줄로 시작한다.
    const fresh = newLineRef.current;
    newLineRef.current = false;
    setLines((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.who === who && !last.shareId && !fresh) {
        return [...prev.slice(0, -1), { ...last, text: joinChunk(last.text, text) }];
      }
      lineId.current += 1;
      return [...prev, { id: lineId.current, who, text: joinChunk('', text) }].slice(-40);
    });
  }, []);

  const clearTimers = useCallback(() => {
    if (redialTimerRef.current !== null) window.clearTimeout(redialTimerRef.current);
    if (attemptTimerRef.current !== null) window.clearTimeout(attemptTimerRef.current);
    redialTimerRef.current = null;
    attemptTimerRef.current = null;
  }, []);

  // 현재 연결만 닫는다. 세션 번호를 올려 이 연결에서 뒤늦게 오는 콜백(onDisconnected 등)을 무시하게 한다.
  const dropClient = useCallback((stash: boolean) => {
    sessionRef.current += 1;
    const client = clientRef.current;
    clientRef.current = null;
    const meter = meterRef.current;
    meterRef.current = null;
    if (meter) {
      const measured = meter.stop();
      if (stash && liveRef.current) stashLatency(measured);
    }
    if (client) void client.disconnect();
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.muted = false;
    }
    setBotSpeaking(false);
  }, []);

  const release = useCallback(() => {
    clearTimers();
    dropClient(true);
    reconnectingRef.current = false;
    setReconnecting(false);
    // 멈춘 채로 끝나면 그 시간도 통화 시간에서 뺀다(서버 CallClock과 같게).
    const since = pausedAtRef.current;
    if (since !== null) setPausedTotal((total) => total + (Date.now() - since));
    pausedAtRef.current = null;
    setPausedAt(null);
  }, [clearTimers, dropClient]);

  const finish = useCallback(
    (reason: EndReason) => {
      release();
      if (!everLiveRef.current) {
        // Ms. Park이 준비되기 전에 끊긴 연결은 통화가 아니다. 요약 대신 다시 걸기를 보여 준다.
        setStatus('error');
        setError('연결이 끊겼어요. 다시 걸어 주세요.');
        return;
      }
      if (!reasonRef.current) reasonRef.current = reason;
      setEndReason(reasonRef.current);
      setStatus('ended');
    },
    [release],
  );

  // 다음 다시 걸기를 예약한다. 횟수를 다 썼으면 지금까지의 통화를 끊긴 것으로 마무리한다(자막은 그대로 남는다).
  const scheduleAttempt = useCallback(() => {
    clearTimers();
    const n = attemptRef.current + 1;
    const delay = redialDelayMs(n);
    if (delay === null) {
      console.info('[call] redial gave up');
      finish('dropped');
      return;
    }
    attemptRef.current = n;
    redialsRef.current += 1;
    console.info(`[call] redial attempt ${n} in ${delay}ms`);
    redialTimerRef.current = window.setTimeout(() => {
      redialTimerRef.current = null;
      if (!reconnectingRef.current || !lastParamsRef.current) return;
      void connectRef.current(lastParamsRef.current, true);
    }, delay);
  }, [clearTimers, finish]);

  const failAttempt = useCallback(() => {
    if (!reconnectingRef.current) return;
    dropClient(false);
    scheduleAttempt();
  }, [dropClient, scheduleAttempt]);

  const beginRedial = useCallback(
    (why: string) => {
      if (reconnectingRef.current || !lastParamsRef.current) return;
      console.info(`[call] connection lost (${why}); redialing`);
      dropClient(false);
      liveRef.current = false;
      healthRef.current = null;
      reconnectingRef.current = true;
      setReconnecting(true);
      attemptRef.current = 0;
      scheduleAttempt();
    },
    [dropClient, scheduleAttempt],
  );

  // 연결이 닫혔을 때: 서버가 끝을 알린 통화나 연결된 적 없는 통화는 그대로 끝내고, 그 밖에는 다시 건다.
  lostRef.current = () => {
    if (reconnectingRef.current) {
      failAttempt();
      return;
    }
    if (!shouldRedial({ everLive: everLiveRef.current, endReason: reasonRef.current })) {
      finish('dropped');
      return;
    }
    beginRedial('disconnected');
  };

  const connectSession = useCallback(
    async (params: DialParams, redial: boolean) => {
      sessionRef.current += 1;
      const sid = sessionRef.current;
      const current = () => sessionRef.current === sid;
      if (!redial) clearPendingLatency();
      meterRef.current?.stop();
      meterRef.current = new LatencyMeter(performance.now());

      if (!audioRef.current) {
        audioRef.current = new Audio();
        audioRef.current.autoplay = true;
      }
      // 사용자가 누른 직후에 재생을 허락받아 둔다(폰 브라우저 자동 재생 제한).
      void audioRef.current.play().catch(() => undefined);

      const client = new PipecatClient({
        transport: new SmallWebRTCTransport(),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onBotReady: () => {
            if (!current()) return;
            liveRef.current = true;
            everLiveRef.current = true;
            healthRef.current = newHealth(Date.now());
            const mic = clientRef.current?.tracks().local.audio;
            if (mic) meterRef.current?.attachMic(mic);
            if (reconnectingRef.current) {
              console.info('[call] redial connected');
              clearTimers();
              reconnectingRef.current = false;
              setReconnecting(false);
              attemptRef.current = 0;
              newLineRef.current = true;
              const fresh = clientRef.current;
              if (fresh && pausedAtRef.current !== null) {
                // 멈춘 채 끊겼다면 새 연결도 멈춘 상태로 맞춘다(서버 시계는 새로 시작했다).
                fresh.enableMic(false);
                if (audioRef.current) audioRef.current.muted = true;
                meterRef.current?.setPaused(true);
                fresh.sendClientMessage('pause');
              } else if (fresh && !micOnRef.current) {
                fresh.enableMic(false);
              }
            } else {
              const now = Date.now();
              liveStartRef.current = now;
              setLiveAt(now);
            }
            setStatus('live');
          },
          onTrackStarted: (track, participant) => {
            if (!current()) return;
            if (track.kind === 'audio') {
              if (participant?.local) {
                meterRef.current?.attachMic(track);
                track.addEventListener('ended', () => recoverMicRef.current());
              }
              else meterRef.current?.attachBot(track);
            }
            // SmallWebRTCTransport는 원격(Ms. Park) 트랙에 participant를 넘기지 않는다. local이 아니면 원격으로 본다.
            if (track.kind === 'audio' && !participant?.local && audioRef.current) {
              audioRef.current.srcObject = new MediaStream([track]);
              audioRef.current.play().then(
                () => setAudioBlocked(false),
                () => setAudioBlocked(true),
              );
            }
          },
          onBotStartedSpeaking: () => current() && setBotSpeaking(true),
          onBotStoppedSpeaking: () => current() && setBotSpeaking(false),
          onRemoteAudioLevel: (level) => current() && setBotLevel(level),
          onLocalAudioLevel: (level) => current() && setUserLevel(level),
          onUserInput: (data) => current() && addChunk('me', data.text),
          onBotOutput: (data) => current() && addChunk('park', data.text),
          onServerMessage: (data) => {
            if (!current()) return;
            if (data?.type === 'mission_complete') {
              const args = data.args || {};
              setResult({
                score: Number(args.score) || 0,
                feedback_pointers: Array.isArray(args.feedback_pointers) ? args.feedback_pointers.map(String) : [],
              });
              reasonRef.current = 'mission_complete';
              const bell = new Audio('/winner-bell.mp3');
              bell.volume = 0.6;
              void bell.play().catch(() => undefined);
              window.setTimeout(() => finish('mission_complete'), MISSION_END_DELAY_MS);
            } else if (data?.type === 'time_limit') {
              reasonRef.current = data.reason === 'pause_limit' ? 'pause_limit' : 'time_limit';
            } else if (data?.type === 'shared_clip') {
              const clip = parseSharedClip(data);
              if (clip) setSharedClips((prev) => (prev.some((c) => clipKey(c) === clipKey(clip)) ? prev : [...prev, clip]));
            } else if (data?.type === 'share_ack') {
              const ack = parseShareAck(data);
              if (ack) {
                setLines((prev) =>
                  prev.map((line) =>
                    line.shareId === ack.id && line.share
                      ? { ...line, share: { url: ack.url ?? line.share.url, title: ack.title || line.share.title, failed: ack.opened === false } }
                      : line,
                  ),
                );
              }
            }
          },
          onDisconnected: () => {
            if (current()) lostRef.current();
          },
          onError: (message) => {
            if (!current()) return;
            const data = message?.data as { message?: string } | string | undefined;
            setError(friendlyError(new Error((typeof data === 'string' ? data : data?.message) || ''), '통화 중 오류가 났어요.'));
          },
        },
      });
      clientRef.current = client;

      if (redial) {
        attemptTimerRef.current = window.setTimeout(() => {
          attemptTimerRef.current = null;
          if (current()) {
            console.info('[call] redial attempt timed out');
            failAttempt();
          }
        }, ATTEMPT_TIMEOUT_MS);
      }

      try {
        await client.connect({
          webrtcRequestParams: {
            endpoint: '/api/offer',
            requestData: {
              system_instruction: params.systemInstruction,
              mode: params.mode,
              voice: params.voice,
              ...(params.partner ? { partner: params.partner } : {}),
              ...(params.summaryInput?.lesson_date ? { lesson_date: params.summaryInput.lesson_date } : {}),
              ...(params.summaryInput?.practice_words?.length ? { practice_words: params.summaryInput.practice_words } : {}),
              ...(redial ? { resume_turns: resumeTurns(linesRef.current) } : {}),
            },
          },
        });
      } catch (e) {
        if (redial) {
          if (current()) failAttempt();
          return;
        }
        release();
        setStatus('error');
        setError(friendlyError(e, '연결하지 못했어요.'));
      }
    },
    [addChunk, clearTimers, failAttempt, finish, release],
  );
  connectRef.current = connectSession;

  const start = useCallback(
    async (systemInstruction: string, mode: CallMode, voice = 'Kore', partner?: string, summaryInput?: SummaryInput) => {
      clearTimers();
      setStatus('connecting');
      setError(null);
      setLines([]);
      setResult(null);
      setEndReason(null);
      setLiveAt(null);
      setPausedAt(null);
      setPausedTotal(0);
      pausedAtRef.current = null;
      setAudioBlocked(false);
      setSharedClips([]);
      reasonRef.current = null;
      liveRef.current = false;
      everLiveRef.current = false;
      reconnectingRef.current = false;
      setReconnecting(false);
      attemptRef.current = 0;
      redialsRef.current = 0;
      newLineRef.current = false;
      liveStartRef.current = null;
      healthRef.current = null;
      micOnRef.current = true;
      lastParamsRef.current = { systemInstruction, mode, voice, partner, summaryInput };
      await connectSession(lastParamsRef.current, false);
    },
    [clearTimers, connectSession],
  );

  // iOS는 상태창·제어 센터를 내리면 웹 페이지 마이크를 멈추고(트랙 muted/ended) 돌아와도 안 살릴 때가 있다.
  // 화면이 다시 보이거나 포커스를 받을 때 마이크가 죽어 있으면 다시 잡고, 멈춘 상대 음성도 다시 튼다.
  const recoverMic = useCallback(() => {
    const client = clientRef.current;
    if (!client || !liveRef.current || pausedAtRef.current !== null || document.visibilityState !== 'visible') return;
    const mic = client.tracks().local.audio;
    if (!mic || mic.readyState === 'ended' || mic.muted) client.updateMic(client.selectedMic.deviceId ?? '');
    const audio = audioRef.current;
    if (audio?.srcObject && audio.paused) {
      audio.play().then(
        () => setAudioBlocked(false),
        () => setAudioBlocked(true),
      );
    }
  }, []);
  recoverMicRef.current = recoverMic;

  useEffect(() => {
    if (status !== 'live') return;
    document.addEventListener('visibilitychange', recoverMic);
    window.addEventListener('focus', recoverMic);
    window.addEventListener('pageshow', recoverMic);
    return () => {
      document.removeEventListener('visibilitychange', recoverMic);
      window.removeEventListener('focus', recoverMic);
      window.removeEventListener('pageshow', recoverMic);
    };
  }, [status, recoverMic]);

  // 1초마다 연결을 살피고 5초마다 품질을 서버에 보낸다. 끊긴 것으로 판정되면 같은 통화를 다시 건다.
  useEffect(() => {
    if (status !== 'live') return;
    let ticks = 0;
    let busy = false;
    const every = Math.max(1, Math.round(TELEMETRY_EVERY_MS / 1000));
    const timer = window.setInterval(async () => {
      if (busy || reconnectingRef.current || !liveRef.current) return;
      const sid = sessionRef.current;
      const client = clientRef.current;
      if (!client) return;
      busy = true;
      try {
        const internals = client.transport as unknown as TransportInternals;
        const pc = internals.pc ?? null;
        let sample: StatsSample = EMPTY_STATS;
        if (pc) {
          try {
            sample = readStats(await pc.getStats());
          } catch {
            // 닫힌 연결은 보고서를 못 준다. 패킷이 없는 것으로 판정한다.
          }
        }
        if (sid !== sessionRef.current) return;
        const now = Date.now();
        const { health, dead } = judgeHealth(
          healthRef.current ?? newHealth(now),
          { inPk: sample.inPk, outPk: sample.outPk, conn: pc?.connectionState, ice: pc?.iceConnectionState },
          now,
          { paused: pausedAtRef.current !== null, visible: document.visibilityState === 'visible' },
        );
        healthRef.current = health;
        ticks += 1;
        if (dead || ticks % every === 0) {
          const payload = telemetryPayload(sample, {
            t: liveStartRef.current ? (now - liveStartRef.current) / 1000 : 0,
            vis: document.visibilityState,
            ice: pc?.iceConnectionState,
            conn: pc?.connectionState,
            dc: internals.dc?.readyState,
            mic: micState(client.tracks().local.audio),
            paused: pausedAtRef.current !== null,
            redials: redialsRef.current,
            dead: (dead as DeadReason | null) ?? undefined,
          });
          try {
            client.sendClientMessage('telemetry', payload);
          } catch {
            // 데이터 채널이 이미 닫혔으면 보낼 수 없다. 다음 판정에서 다시 건다.
          }
        }
        if (dead) beginRedial(dead);
      } finally {
        busy = false;
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [status, beginRedial]);

  const hangUp = useCallback(() => finish('hangup'), [finish]);

  // 브라우저가 자동 재생을 막았을 때 사용자가 누른 버튼에서 다시 재생한다.
  const resumeAudio = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.play().then(
      () => setAudioBlocked(false),
      () => setAudioBlocked(true),
    );
  }, []);

  const pause = useCallback(() => {
    const client = clientRef.current;
    if (!client || !liveRef.current || pausedAtRef.current !== null) return;
    micBeforePauseRef.current = client.isMicEnabled;
    client.enableMic(false);
    if (audioRef.current) audioRef.current.muted = true;
    meterRef.current?.setPaused(true);
    pausedAtRef.current = Date.now();
    setPausedAt(pausedAtRef.current);
    client.sendClientMessage('pause');
  }, []);

  const resume = useCallback(() => {
    const client = clientRef.current;
    const since = pausedAtRef.current;
    if (!client || since === null) return;
    client.enableMic(micBeforePauseRef.current);
    if (audioRef.current) audioRef.current.muted = false;
    meterRef.current?.setPaused(false);
    pausedAtRef.current = null;
    setPausedTotal((total) => total + (Date.now() - since));
    setPausedAt(null);
    client.sendClientMessage('resume');
    recoverMic();
  }, [recoverMic]);

  // 통화 중 글·링크 보내기. 보냈으면 true. 자막에는 바로 "나" 말풍선으로 넣고, 서버가 읽은 결과(share_ack)가 오면 칩 제목을 고친다.
  const share = useCallback((raw: string): boolean => {
    const client = clientRef.current;
    const text = raw.trim().slice(0, SHARE_MAX);
    if (!client || !liveRef.current || !text) return false;
    shareCount.current += 1;
    const id = String(shareCount.current);
    const url = firstUrl(text);
    lineId.current += 1;
    const line: CaptionLine = { id: lineId.current, who: 'me', text, shareId: id, ...(url ? { share: { url } } : {}) };
    setLines((prev) => [...prev, line].slice(-40));
    client.sendClientMessage('share', { text, id });
    return true;
  }, []);

  const toggleMic = useCallback(() => {
    const client = clientRef.current;
    if (!client || pausedAtRef.current !== null) return;
    const next = !client.isMicEnabled;
    client.enableMic(next);
    micOnRef.current = next;
    setMicOn(next);
  }, []);

  useEffect(
    () => () => {
      clearTimers();
      sessionRef.current += 1;
      const client = clientRef.current;
      clientRef.current = null;
      meterRef.current?.stop();
      meterRef.current = null;
      if (client) void client.disconnect();
    },
    [clearTimers],
  );

  return { status, lines, botSpeaking, botLevel, userLevel, micOn, error, result, endReason, liveAt, audioBlocked, reconnecting, paused: pausedAt !== null, pausedAt, pausedTotal, sharedClips, start, hangUp, pause, resume, toggleMic, resumeAudio, share };
}
