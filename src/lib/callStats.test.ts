import { describe, expect, test } from 'bun:test';
import { EMPTY_STATS, readStats, telemetryPayload, type StatsLike } from './callStats';

function report(items: Record<string, unknown>[]): StatsLike {
  return { forEach: (cb) => items.forEach((item) => cb(item, String(item.id))) };
}

const chromeReport = report([
  { id: 'T01', type: 'transport', selectedCandidatePairId: 'CP1' },
  { id: 'CP1', type: 'candidate-pair', state: 'succeeded', nominated: true, localCandidateId: 'L1', remoteCandidateId: 'R1', currentRoundTripTime: 0.2134, bytesSent: 1000, bytesReceived: 900 },
  { id: 'CP2', type: 'candidate-pair', state: 'succeeded', nominated: true, localCandidateId: 'L2', remoteCandidateId: 'R2', currentRoundTripTime: 0.05, bytesSent: 99999, bytesReceived: 99999 },
  { id: 'L1', type: 'local-candidate', candidateType: 'host', protocol: 'udp', networkType: 'vpn', address: '100.64.0.1' },
  { id: 'R1', type: 'remote-candidate', candidateType: 'host', protocol: 'udp', address: '100.64.0.2' },
  { id: 'L2', type: 'local-candidate', candidateType: 'relay', protocol: 'udp' },
  { id: 'R2', type: 'remote-candidate', candidateType: 'relay', protocol: 'udp' },
  { id: 'OA', type: 'outbound-rtp', kind: 'audio', packetsSent: 1750, bytesSent: 40960 },
  { id: 'OV', type: 'outbound-rtp', kind: 'video', packetsSent: 5, bytesSent: 500 },
  { id: 'IA', type: 'inbound-rtp', kind: 'audio', packetsReceived: 1700, packetsLost: 3, jitter: 0.0123, bytesReceived: 38912, jitterBufferDelay: 12, jitterBufferEmittedCount: 200 },
  { id: 'RA', type: 'remote-inbound-rtp', kind: 'audio', packetsLost: 2, jitter: 0.005 },
]);

describe('readStats', () => {
  test('transport가 가리키는 후보 쌍과 오디오 패킷 수를 읽는다', () => {
    expect(readStats(chromeReport)).toEqual({
      pair: 'host/host/udp',
      net: 'vpn',
      rttMs: 213,
      outPk: 1750,
      outKb: 40,
      inPk: 1700,
      inLost: 3,
      inJitMs: 12,
      inKb: 38,
      jbufMs: 60,
      rinLost: 2,
      rinJitMs: 5,
    });
  });

  test('transport 표시가 없으면 selected 쌍, 그것도 없으면 가장 많이 쓴 성공한 쌍을 고른다', () => {
    const items = [
      { id: 'CP1', type: 'candidate-pair', state: 'succeeded', nominated: true, localCandidateId: 'L1', remoteCandidateId: 'R1', bytesSent: 10, bytesReceived: 10 },
      { id: 'CP2', type: 'candidate-pair', state: 'succeeded', nominated: true, localCandidateId: 'L2', remoteCandidateId: 'R2', bytesSent: 500, bytesReceived: 500 },
      { id: 'L1', type: 'local-candidate', candidateType: 'host', protocol: 'udp' },
      { id: 'R1', type: 'remote-candidate', candidateType: 'host', protocol: 'udp' },
      { id: 'L2', type: 'local-candidate', candidateType: 'relay', protocol: 'udp' },
      { id: 'R2', type: 'remote-candidate', candidateType: 'srflx', protocol: 'udp' },
    ];
    expect(readStats(report(items)).pair).toBe('relay/srflx/udp');
    const selected = items.map((item) => (item.id === 'CP1' ? { ...item, selected: true } : item));
    expect(readStats(report(selected)).pair).toBe('host/host/udp');
  });

  test('IP 주소는 결과에 들어가지 않는다', () => {
    expect(JSON.stringify(readStats(chromeReport))).not.toContain('100.64');
  });

  test('비어 있거나 일부만 있는 보고서는 null로 채운다', () => {
    expect(readStats(report([]))).toEqual(EMPTY_STATS);
    const partial = readStats(report([{ id: 'OA', type: 'outbound-rtp', kind: 'audio', packetsSent: 7 }]));
    expect(partial.outPk).toBe(7);
    expect(partial.inPk).toBeNull();
    expect(partial.pair).toBeNull();
  });

  test('숫자가 아닌 값(NaN, 문자열)은 null이다', () => {
    const odd = readStats(report([{ id: 'IA', type: 'inbound-rtp', kind: 'audio', packetsReceived: 'many', jitter: Number.NaN }]));
    expect(odd.inPk).toBeNull();
    expect(odd.inJitMs).toBeNull();
  });
});

describe('telemetryPayload', () => {
  const ctx = { t: 35.4, vis: 'visible', ice: 'connected', conn: 'connected', dc: 'open', mic: 'live', paused: false, redials: 0 };

  test('값이 있는 항목만 평평한 묶음으로 만든다', () => {
    const payload = telemetryPayload(readStats(chromeReport), ctx);
    expect(payload).toEqual({
      t: 35,
      vis: 'visible',
      ice: 'connected',
      conn: 'connected',
      dc: 'open',
      pair: 'host/host/udp',
      net: 'vpn',
      rtt: 213,
      out_pk: 1750,
      out_kb: 40,
      in_pk: 1700,
      in_lost: 3,
      in_jit: 12,
      in_kb: 38,
      jbuf: 60,
      rin_lost: 2,
      rin_jit: 5,
      mic: 'live',
      paused: 0,
      rd: 0,
    });
  });

  test('보고서가 비어도 상태 항목은 남고, 끊김 이유와 일시정지가 실린다', () => {
    const payload = telemetryPayload(EMPTY_STATS, { ...ctx, paused: true, redials: 2, dead: 'silence' });
    expect(payload).toEqual({ t: 35, vis: 'visible', ice: 'connected', conn: 'connected', dc: 'open', mic: 'live', paused: 1, rd: 2, dead: 'silence' });
  });
});
