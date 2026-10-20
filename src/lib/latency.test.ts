import { describe, expect, test } from 'bun:test';
import { detectTurns, summarizeLatency, TurnDetector } from './latency';

// [길이 ms, 마이크 RMS, 봇 RMS] 구간을 20ms 간격 샘플로 펼쳐 감지기에 넣는다. 숫자 하나는 샘플이 없는 틈(ms)이다.
type Seg = [number, number, number] | number;

const NOISE = 0.002; // 조용한 방의 배경 소음
const VOICE = 0.1;
const BOT = 0.2;

function run(segs: Seg[], step = 20): TurnDetector {
  const d = new TurnDetector();
  let t = 0;
  for (const seg of segs) {
    if (typeof seg === 'number') {
      t += seg;
      continue;
    }
    const [ms, mic, bot] = seg;
    for (let e = 0; e < ms; e += step) {
      d.push(t, mic, bot);
      t += step;
    }
  }
  return d;
}

const quiet = (ms: number): Seg => [ms, NOISE, 0];
const learner = (ms: number, level = VOICE): Seg => [ms, level, 0];
const bot = (ms: number, mic = NOISE): Seg => [ms, mic, BOT];

describe('TurnDetector', () => {
  test('S1 정상 두 턴은 1500ms씩 잰다', () => {
    const d = run([quiet(1000), learner(2000), quiet(1500), bot(2000), quiet(1000), learner(2000), quiet(1500), bot(2000)]);
    expect(d.turns).toEqual([1500, 1500]);
    expect(d.cutoffs).toBe(0);
  });

  test('S2 문장 중간 700ms 멈춤에 봇이 끼어들고 학습자가 이어 말하면 끊김이다', () => {
    const d = run([quiet(1000), learner(2000), quiet(700), bot(300), [1200, VOICE, BOT], bot(500)]);
    expect(d.turns).toEqual([]);
    expect(d.cutoffs).toBe(1);
  });

  test('S3 봇이 시작하는 순간 학습자가 다시 말해도 끊김이다', () => {
    const d = run([quiet(1000), learner(2000), quiet(600), [2000, VOICE, BOT]]);
    expect(d.turns).toEqual([]);
    expect(d.cutoffs).toBe(1);
  });

  test('S4 주변 소음이 0.03으로 오른 뒤에도 이후 턴을 잰다', () => {
    const noisy = (ms: number): Seg => [ms, 0.03, 0];
    const d = run([
      quiet(1000), learner(2000), quiet(1500), bot(2000), // 조용할 때의 첫 턴
      noisy(7000), // 소음이 올라가 5초 넘게 문턱 위에 머문다
      [1500, 0.3, 0], noisy(1000), [1500, 0.03, BOT],
      [1500, 0.3, 0], noisy(1000), [1500, 0.03, BOT],
    ]);
    expect(d.turns).toEqual([1500, 1000, 1000]);
    expect(d.cutoffs).toBe(0);
  });

  test('S5 작은 목소리(0.015)도 턴으로 잰다', () => {
    const d = run([quiet(1000), learner(2000, 0.015), quiet(1000), bot(2000)]);
    expect(d.turns).toEqual([1000]);
    expect(d.cutoffs).toBe(0);
  });

  test('S6 샘플 간격이 1초(백그라운드 탭)이면 턴을 만들지 않는다', () => {
    const d = new TurnDetector();
    let t = 0;
    const feed = (n: number, mic: number, botLevel: number) => {
      for (let i = 0; i < n; i++, t += 1000) d.push(t, mic, botLevel);
    };
    feed(2, NOISE, 0);
    feed(4, VOICE, 0);
    feed(3, NOISE, 0);
    feed(5, NOISE, BOT);
    expect(d.turns).toEqual([]);
    expect(d.cutoffs).toBe(0);
  });

  test('L3 샘플 사이가 100ms를 넘게 비면 그 틈을 가로지르는 턴은 없다', () => {
    const d = run([quiet(1000), learner(2000), quiet(300), 500, bot(1000)]);
    expect(d.turns).toEqual([]);
    expect(d.cutoffs).toBe(0);
  });

  test('S7 봇 말 중간의 150ms 숨은 가짜 턴을 만들지 않는다', () => {
    const d = run([quiet(1000), learner(2000), quiet(1500), bot(1000), quiet(150), bot(1000)]);
    expect(d.turns).toEqual([1500]);
    expect(d.cutoffs).toBe(0);
  });

  test('S8 봇이 끝난 뒤 300ms 에코 꼬리는 가짜 턴이나 끊김이 아니다', () => {
    const d = run([quiet(1000), learner(2000), quiet(1500), bot(2000), [300, 0.05, 0], quiet(2000)]);
    expect(d.turns).toEqual([1500]);
    expect(d.cutoffs).toBe(0);
  });
});

describe('detectTurns', () => {
  const samples = (botAtMs: number) => {
    const out = [];
    for (let t = 0; t < botAtMs + 400; t += 20) out.push({ t, mic: NOISE, bot: t >= botAtMs ? BOT : 0 });
    return out;
  };

  test('첫소리는 통화 버튼 시각부터 잰다', () => {
    expect(detectTurns(samples(3000)).first_audio_ms).toBe(3000);
    expect(detectTurns(samples(3000), 1000).first_audio_ms).toBe(2000);
  });

  test('첫소리가 20초를 넘으면 null이다', () => {
    expect(detectTurns(samples(21000)).first_audio_ms).toBeNull();
  });

  test('결과에 끊김 횟수가 들어간다', () => {
    expect(detectTurns(samples(3000)).cutoffs).toBe(0);
  });
});

describe('summarizeLatency', () => {
  test('끊김 횟수를 그대로 싣는다', () => {
    const s = summarizeLatency({ turns_ms: [900, 1100, 1500], first_audio_ms: 2000, cutoffs: 2 });
    expect(s).toEqual({ median_ms: 1100, p90_ms: 1500, turns: 3, first_audio_ms: 2000, cutoffs: 2 });
  });
});
