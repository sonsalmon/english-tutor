import { PipecatClient } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';
import { useCallback, useEffect, useRef, useState } from 'react';

export type CallMode = 'mission' | 'freetalk' | 'teachback';
export type CallStatus = 'ready' | 'connecting' | 'live' | 'ended' | 'error';
export type Speaker = 'me' | 'park';
export type CaptionLine = { id: number; who: Speaker; text: string };
export type MissionResult = { score: number; feedback_pointers: string[] };
export type EndReason = 'hangup' | 'mission_complete' | 'time_limit' | 'dropped';

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

  const clientRef = useRef<PipecatClient | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const reasonRef = useRef<EndReason | null>(null);
  const lineId = useRef(0);

  const addChunk = useCallback((who: Speaker, chunk: string) => {
    if (!chunk || !chunk.replace(NOISE_MARK, '').trim()) return;
    setLines((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.who === who) {
        return [...prev.slice(0, -1), { ...last, text: joinChunk(last.text, chunk) }];
      }
      lineId.current += 1;
      return [...prev, { id: lineId.current, who, text: joinChunk('', chunk) }].slice(-40);
    });
  }, []);

  const finish = useCallback((reason: EndReason) => {
    if (!reasonRef.current) reasonRef.current = reason;
    setEndReason(reasonRef.current);
    setStatus('ended');
    setBotSpeaking(false);
    const client = clientRef.current;
    clientRef.current = null;
    if (client) void client.disconnect();
    if (audioRef.current) audioRef.current.srcObject = null;
  }, []);

  const start = useCallback(
    async (systemInstruction: string, mode: CallMode) => {
      setStatus('connecting');
      setError(null);
      setLines([]);
      setResult(null);
      setEndReason(null);
      reasonRef.current = null;

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
          onBotReady: () => setStatus('live'),
          onTrackStarted: (track, participant) => {
            if (track.kind === 'audio' && participant && !participant.local && audioRef.current) {
              audioRef.current.srcObject = new MediaStream([track]);
              void audioRef.current.play().catch(() => undefined);
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
              reasonRef.current = 'time_limit';
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
            requestData: { system_instruction: systemInstruction, mode, voice: 'Puck' },
          },
        });
      } catch (e) {
        clientRef.current = null;
        setStatus('error');
        setError(e instanceof Error ? e.message : '연결하지 못했어요.');
      }
    },
    [addChunk, finish],
  );

  const hangUp = useCallback(() => finish('hangup'), [finish]);

  const toggleMic = useCallback(() => {
    const client = clientRef.current;
    if (!client) return;
    const next = !client.isMicEnabled;
    client.enableMic(next);
    setMicOn(next);
  }, []);

  useEffect(
    () => () => {
      const client = clientRef.current;
      clientRef.current = null;
      if (client) void client.disconnect();
    },
    [],
  );

  return { status, lines, botSpeaking, botLevel, userLevel, micOn, error, result, endReason, start, hangUp, toggleMic };
}
