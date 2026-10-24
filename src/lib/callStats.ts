// 통화 연결 품질 수집: RTCPeerConnection.getStats() 보고서에서 필요한 값만 뽑아 서버로 보낼 작은 묶음을 만든다.
// 화면·네트워크와 무관한 순수 함수라 가짜 보고서로 시험한다. 주소(IP)는 읽지도 보내지도 않는다.

type Rec = Record<string, unknown>;
export type StatsLike = { forEach(cb: (value: Rec, key: string) => void): void };

export type StatsSample = {
  pair: string | null; // 선택된 후보 쌍: "host/host/udp", "relay/host/udp"
  net: string | null; // 내 쪽 네트워크 종류: wifi, cellular, vpn ...
  rttMs: number | null;
  outPk: number | null; // 내가 보낸 마이크 오디오 패킷(누적)
  outKb: number | null;
  inPk: number | null; // 상대 오디오 패킷(누적)
  inLost: number | null;
  inJitMs: number | null;
  inKb: number | null;
  jbufMs: number | null; // 받는 쪽 지터 버퍼의 평균 대기(누적 평균)
  rinLost: number | null; // 서버가 내 오디오에서 잃었다고 알린 패킷
  rinJitMs: number | null;
};

export const EMPTY_STATS: StatsSample = {
  pair: null,
  net: null,
  rttMs: null,
  outPk: null,
  outKb: null,
  inPk: null,
  inLost: null,
  inJitMs: null,
  inKb: null,
  jbufMs: null,
  rinLost: null,
  rinJitMs: null,
};

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null;
}

const ms = (seconds: unknown) => {
  const n = num(seconds);
  return n === null ? null : Math.round(n * 1000);
};

const kb = (bytes: unknown) => {
  const n = num(bytes);
  return n === null ? null : Math.round(n / 1024);
};

function isAudio(r: Rec): boolean {
  return (r.kind ?? r.mediaType) === 'audio';
}

// 선택된 후보 쌍: transport.selectedCandidatePairId(Chrome) → selected 표시(Safari) → 성공한 쌍 중 가장 많이 쓴 쌍.
function pickPair(all: Rec[], byId: Map<string, Rec>): Rec | null {
  const transport = all.find((r) => r.type === 'transport' && str(r.selectedCandidatePairId));
  const chosen = transport ? byId.get(String(transport.selectedCandidatePairId)) : undefined;
  if (chosen) return chosen;
  const pairs = all.filter((r) => r.type === 'candidate-pair');
  const selected = pairs.find((r) => r.selected === true);
  if (selected) return selected;
  const ok = pairs.filter((r) => r.state === 'succeeded' && r.nominated !== false);
  ok.sort((a, b) => (num(b.bytesReceived) ?? 0) + (num(b.bytesSent) ?? 0) - ((num(a.bytesReceived) ?? 0) + (num(a.bytesSent) ?? 0)));
  return ok[0] ?? null;
}

export function readStats(report: StatsLike): StatsSample {
  const all: Rec[] = [];
  const byId = new Map<string, Rec>();
  report.forEach((value, key) => {
    all.push(value);
    byId.set(String(value.id ?? key), value);
  });
  const sample: StatsSample = { ...EMPTY_STATS };

  const pair = pickPair(all, byId);
  if (pair) {
    const local = byId.get(String(pair.localCandidateId));
    const remote = byId.get(String(pair.remoteCandidateId));
    const proto = str(local?.protocol) ?? str(remote?.protocol);
    sample.pair = `${str(local?.candidateType) ?? '?'}/${str(remote?.candidateType) ?? '?'}/${proto ?? '?'}`;
    sample.net = str(local?.networkType);
    sample.rttMs = ms(pair.currentRoundTripTime);
  }

  const out = all.find((r) => r.type === 'outbound-rtp' && isAudio(r));
  if (out) {
    sample.outPk = num(out.packetsSent);
    sample.outKb = kb(out.bytesSent);
  }
  const input = all.find((r) => r.type === 'inbound-rtp' && isAudio(r));
  if (input) {
    sample.inPk = num(input.packetsReceived);
    sample.inLost = num(input.packetsLost);
    sample.inJitMs = ms(input.jitter);
    sample.inKb = kb(input.bytesReceived);
    const delay = num(input.jitterBufferDelay);
    const emitted = num(input.jitterBufferEmittedCount);
    if (delay !== null && emitted) sample.jbufMs = Math.round((delay / emitted) * 1000);
  }
  const rin = all.find((r) => r.type === 'remote-inbound-rtp' && isAudio(r));
  if (rin) {
    sample.rinLost = num(rin.packetsLost);
    sample.rinJitMs = ms(rin.jitter);
  }
  return sample;
}

export type TelemetryContext = {
  t: number; // 통화가 시작된 뒤 지난 초
  vis: string; // document.visibilityState
  ice?: string;
  conn?: string;
  dc?: string;
  mic: string; // live, off, muted, ended, none
  paused: boolean;
  redials: number; // 이 통화에서 다시 건 횟수
  dead?: string; // 끊김으로 판정한 이유(있을 때만)
};

// 서버 call_bot.format_telemetry가 읽는 평평한 묶음. 값이 없는 항목은 뺀다.
export function telemetryPayload(s: StatsSample, c: TelemetryContext): Record<string, string | number> {
  const out: Record<string, string | number> = { t: Math.max(0, Math.round(c.t)), vis: c.vis };
  const put = (key: string, value: string | number | null | undefined) => {
    if (value !== null && value !== undefined && value !== '') out[key] = value;
  };
  put('ice', c.ice);
  put('conn', c.conn);
  put('dc', c.dc);
  put('pair', s.pair);
  put('net', s.net);
  put('rtt', s.rttMs);
  put('out_pk', s.outPk);
  put('out_kb', s.outKb);
  put('in_pk', s.inPk);
  put('in_lost', s.inLost);
  put('in_jit', s.inJitMs);
  put('in_kb', s.inKb);
  put('jbuf', s.jbufMs);
  put('rin_lost', s.rinLost);
  put('rin_jit', s.rinJitMs);
  put('mic', c.mic);
  out.paused = c.paused ? 1 : 0;
  put('rd', c.redials);
  put('dead', c.dead);
  return out;
}
