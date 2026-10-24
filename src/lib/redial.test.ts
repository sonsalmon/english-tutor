import { describe, expect, test } from 'bun:test';
import {
  DISCONNECTED_DEAD_MS,
  FAILED_DEAD_MS,
  MAX_REDIALS,
  SILENCE_DEAD_MS,
  judgeHealth,
  newHealth,
  redialDelayMs,
  shouldRedial,
  type Health,
  type HealthInput,
} from './redial';

const alive = { paused: false, visible: true };
const flat: HealthInput = { inPk: 100, outPk: 100, conn: 'connected', ice: 'connected' };

function run(steps: { at: number; input: HealthInput; ctx?: { paused: boolean; visible: boolean } }[], start = 0) {
  let health: Health = newHealth(start);
  let dead = null as ReturnType<typeof judgeHealth>['dead'];
  for (const step of steps) {
    const result = judgeHealth(health, step.input, step.at, step.ctx ?? alive);
    health = result.health;
    dead = result.dead;
  }
  return dead;
}

describe('judgeHealth: 오디오 패킷이 멈춘 통화', () => {
  test('패킷이 계속 늘면 오래 지나도 끊긴 것이 아니다', () => {
    const steps = Array.from({ length: 30 }, (_, i) => ({ at: i * 1000, input: { ...flat, inPk: 100 + i * 50, outPk: 100 + i * 50 } }));
    expect(run(steps)).toBeNull();
  });

  test('받는 쪽만 멈춰도 보내는 마이크 패킷이 늘면 끊긴 것이 아니다', () => {
    const steps = Array.from({ length: 20 }, (_, i) => ({ at: i * 1000, input: { ...flat, outPk: 100 + i * 50 } }));
    expect(run(steps)).toBeNull();
  });

  test('받는 패킷과 보내는 패킷이 모두 8초 멈추면 silence로 끊긴 것이다', () => {
    const steps = [{ at: 0, input: flat }, { at: 1000, input: flat }, { at: SILENCE_DEAD_MS - 1, input: flat }];
    expect(run(steps)).toBeNull();
    expect(run([...steps, { at: SILENCE_DEAD_MS, input: flat }])).toBe('silence');
  });

  test('멈췄다가 패킷이 다시 늘면 시간을 새로 센다', () => {
    const steps = [
      { at: 0, input: flat },
      { at: 6000, input: flat },
      { at: 7000, input: { ...flat, inPk: 150 } },
      { at: 14000, input: { ...flat, inPk: 150 } },
    ];
    expect(run(steps)).toBeNull();
  });

  test('연결을 새로 만들어 누적 수가 줄어도 진행으로 본다', () => {
    const steps = [
      { at: 0, input: { ...flat, inPk: 5000, outPk: 5000 } },
      { at: 7000, input: { ...flat, inPk: 5000, outPk: 5000 } },
      { at: 8000, input: { ...flat, inPk: 3, outPk: 3 } },
      { at: 15000, input: { ...flat, inPk: 3, outPk: 3 } },
    ];
    expect(run(steps)).toBeNull();
  });

  test('보고서를 못 읽어도(패킷 수 null) 8초가 지나면 끊긴 것이다', () => {
    const none: HealthInput = { inPk: null, outPk: null };
    expect(run([{ at: 0, input: none }, { at: SILENCE_DEAD_MS, input: none }])).toBe('silence');
  });

  test('일시정지 중에는 멈춰 있어도 끊긴 것이 아니다', () => {
    const paused = { paused: true, visible: true };
    const steps = [{ at: 0, input: flat, ctx: paused }, { at: 60000, input: flat, ctx: paused }];
    expect(run(steps)).toBeNull();
  });

  test('일시정지를 풀면 그 시각부터 다시 센다', () => {
    const paused = { paused: true, visible: true };
    const steps = [
      { at: 0, input: flat, ctx: paused },
      { at: 60000, input: flat, ctx: paused },
      { at: 60000 + SILENCE_DEAD_MS - 1, input: flat },
    ];
    expect(run(steps)).toBeNull();
    expect(run([...steps, { at: 60000 + SILENCE_DEAD_MS, input: flat }])).toBe('silence');
  });

  test('화면이 숨은 동안은 세지 않고, 돌아온 뒤부터 다시 센다', () => {
    const hidden = { paused: false, visible: false };
    const steps = [
      { at: 0, input: flat },
      { at: 40000, input: flat, ctx: hidden },
      { at: 40000 + SILENCE_DEAD_MS - 1, input: flat },
    ];
    expect(run(steps)).toBeNull();
    expect(run([...steps, { at: 40000 + SILENCE_DEAD_MS, input: flat }])).toBe('silence');
  });
});

describe('judgeHealth: 연결 상태', () => {
  const growing = (at: number): HealthInput => ({ inPk: at, outPk: at });

  test('failed가 3초 이어지면 패킷이 늘어도 끊긴 것이다', () => {
    const bad = (at: number): HealthInput => ({ ...growing(at), conn: 'failed' });
    expect(run([{ at: 0, input: bad(0) }, { at: FAILED_DEAD_MS - 1, input: bad(FAILED_DEAD_MS - 1) }])).toBeNull();
    expect(run([{ at: 0, input: bad(0) }, { at: FAILED_DEAD_MS, input: bad(FAILED_DEAD_MS) }])).toBe('failed');
  });

  test('closed도 failed와 같게 본다(페이지가 PC를 닫은 경우)', () => {
    const bad = (at: number): HealthInput => ({ ...growing(at), conn: 'closed' });
    expect(run([{ at: 0, input: bad(0) }, { at: FAILED_DEAD_MS, input: bad(FAILED_DEAD_MS) }])).toBe('failed');
  });

  test('ICE가 failed인 경우도 끊긴 것이다', () => {
    const bad = (at: number): HealthInput => ({ ...growing(at), conn: 'connected', ice: 'failed' });
    expect(run([{ at: 0, input: bad(0) }, { at: FAILED_DEAD_MS, input: bad(FAILED_DEAD_MS) }])).toBe('failed');
  });

  test('disconnected는 8초 넘게 이어질 때만 끊긴 것이다', () => {
    const bad = (at: number): HealthInput => ({ ...growing(at), conn: 'disconnected' });
    expect(run([{ at: 0, input: bad(0) }, { at: DISCONNECTED_DEAD_MS - 1, input: bad(DISCONNECTED_DEAD_MS - 1) }])).toBeNull();
    expect(run([{ at: 0, input: bad(0) }, { at: DISCONNECTED_DEAD_MS, input: bad(DISCONNECTED_DEAD_MS) }])).toBe('disconnected');
  });

  test('disconnected가 풀리면 시간을 새로 센다', () => {
    const steps = [
      { at: 0, input: { ...growing(0), conn: 'disconnected' } },
      { at: 6000, input: { ...growing(6000), conn: 'connected' } },
      { at: 7000, input: { ...growing(7000), conn: 'disconnected' } },
      { at: 7000 + DISCONNECTED_DEAD_MS - 1, input: { ...growing(7000 + DISCONNECTED_DEAD_MS - 1), conn: 'disconnected' } },
    ];
    expect(run(steps)).toBeNull();
  });

  test('연결 상태가 정상이고 패킷이 늘면 끊긴 것이 아니다', () => {
    expect(run([{ at: 0, input: growing(0) }, { at: 100000, input: growing(100000) }])).toBeNull();
  });
});

describe('다시 걸기 규칙', () => {
  test('시도는 3번까지이고 점점 길게 기다린다', () => {
    const delays = [1, 2, 3].map((n) => redialDelayMs(n));
    expect(delays).toEqual([1000, 3000, 7000]);
    expect(delays[0]! < delays[1]! && delays[1]! < delays[2]!).toBe(true);
    expect(redialDelayMs(MAX_REDIALS + 1)).toBeNull();
    expect(redialDelayMs(0)).toBeNull();
  });

  test('연결된 적이 있고 서버가 끝을 알리지 않았을 때만 다시 건다', () => {
    expect(shouldRedial({ everLive: true, endReason: null })).toBe(true);
    expect(shouldRedial({ everLive: false, endReason: null })).toBe(false);
    expect(shouldRedial({ everLive: true, endReason: 'time_limit' })).toBe(false);
    expect(shouldRedial({ everLive: true, endReason: 'mission_complete' })).toBe(false);
  });
});
