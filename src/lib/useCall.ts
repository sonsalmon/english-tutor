import { PipecatClient } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';
import { useCallback, useEffect, useRef, useState } from 'react';
import { LatencyMeter, clearPendingLatency, stashLatency } from './latency';
import { cleanLearnerText } from './transcript';

// 통화가 끝난 뒤 서버가 스스로 정리를 걸 때 쓰는 입력. 통화를 걸 때 서버에 미리 알려 둔다.
export type SummaryInput = { lesson_date?: string; practice_words?: string[] };
export type CallMode = 'mission' | 'freetalk' | 'teachback' | 'smalltalk';
export type CallStatus = 'ready' | 'connecting' | 'live' | 'ended' | 'error';
export type Speaker = 'me' | 'park';
export type CaptionLine = { id: number; who: Speaker; text: string };
export type MissionResult = { score: number; feedback_pointers: string[] };
export type EndReason = 'hangup' | 'mission_complete' | 'time_limit' | 'pause_limit' | 'dropped';

const MISSION_END_DELAY_MS = 3500;

// Gemini 받아쓰기가 잡음을 `{}`로 내보낼 때가 있다(서버 call_bot.NOISE_MARK_RE와 같은 규칙).
const NOISE_MARK = /\{\s*\}/g;

function joinChunk(prev: string, chunk: string): string {
  return `${prev} ${chunk.replace(NOISE_MARK, ' ')}`.replace(/\s+/g, ' ').trim();
}

export function useCall() {
  const [status, setStatus] = useState<CallStatus>('ready');
  const [lines, setLines] = useState<CaptionLine[]>([]);
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [botLevel, setBotLevel] = useState(0);
  const [userLevel, setUserLevel] = useState(0);
  const [micOn, setMicOn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MissionResult | null>(null);
  const [endReason, setEndReason] = useState<EndReason | null>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
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

  const addChunk = useCallback((who: Speaker, chunk: string) => {
    if (!chunk || !chunk.replace(NOISE_MARK, '').trim()) return;
    const text = who === 'me' ? cleanLearnerText(chunk) : chunk;
    setLines((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.who === who) {
        return [...prev.slice(0, -1), { ...last, text: joinChunk(last.text, text) }];
      }
      lineId.current += 1;
      return [...prev, { id: lineId.current, who, text: joinChunk('', text) }].slice(-40);
    });
  }, []);

  const release = useCallback(() => {
    const client = clientRef.current;
    clientRef.current = null;
    const meter = meterRef.current;
    meterRef.current = null;
    if (meter) {
      const measured = meter.stop();
      if (liveRef.current) stashLatency(measured);
    }
    if (client) void client.disconnect();
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.muted = false;
    }
    // 멈춘 채로 끝나면 그 시간도 통화 시간에서 뺀다(서버 CallClock과 같게).
    const since = pausedAtRef.current;
    if (since !== null) setPausedTotal((total) => total + (Date.now() - since));
    pausedAtRef.current = null;
    setPausedAt(null);
    setBotSpeaking(false);
  }, []);

  const finish = useCallback(
    (reason: EndReason) => {
      release();
      if (!liveRef.current) {
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

  const start = useCallback(
    async (systemInstruction: string, mode: CallMode, voice = 'Kore', partner?: string, summaryInput?: SummaryInput) => {
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
      reasonRef.current = null;
      liveRef.current = false;
      clearPendingLatency();
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
            liveRef.current = true;
            const mic = clientRef.current?.tracks().local.audio;
            if (mic) meterRef.current?.attachMic(mic);
            setLiveAt(Date.now());
            setStatus('live');
          },
          onTrackStarted: (track, participant) => {
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
          onBotStartedSpeaking: () => setBotSpeaking(true),
          onBotStoppedSpeaking: () => setBotSpeaking(false),
          onRemoteAudioLevel: (level) => setBotLevel(level),
          onLocalAudioLevel: (level) => setUserLevel(level),
          onUserInput: (data) => addChunk('me', data.text),
          onBotOutput: (data) => addChunk('park', data.text),
          onServerMessage: (data) => {
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
            }
          },
          onDisconnected: () => finish('dropped'),
          onError: (message) => {
            const data = message?.data as { message?: string } | string | undefined;
            setError((typeof data === 'string' ? data : data?.message) || '통화 중 오류가 났어요.');
          },
        },
      });
      clientRef.current = client;

      try {
        await client.connect({
          webrtcRequestParams: {
            endpoint: '/api/offer',
            requestData: {
              system_instruction: systemInstruction,
              mode,
              voice,
              ...(partner ? { partner } : {}),
              ...(summaryInput?.lesson_date ? { lesson_date: summaryInput.lesson_date } : {}),
              ...(summaryInput?.practice_words?.length ? { practice_words: summaryInput.practice_words } : {}),
            },
          },
        });
      } catch (e) {
        release();
        setStatus('error');
        setError(e instanceof Error ? e.message : '연결하지 못했어요.');
      }
    },
    [addChunk, finish, release],
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
  const recoverMicRef = useRef(recoverMic);
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

  const toggleMic = useCallback(() => {
    const client = clientRef.current;
    if (!client || pausedAtRef.current !== null) return;
    const next = !client.isMicEnabled;
    client.enableMic(next);
    setMicOn(next);
  }, []);

  useEffect(
    () => () => {
      const client = clientRef.current;
      clientRef.current = null;
      meterRef.current?.stop();
      meterRef.current = null;
      if (client) void client.disconnect();
    },
    [],
  );

  return { status, lines, botSpeaking, botLevel, userLevel, micOn, error, result, endReason, liveAt, audioBlocked, paused: pausedAt !== null, pausedAt, pausedTotal, start, hangUp, pause, resume, toggleMic, resumeAudio };
}
