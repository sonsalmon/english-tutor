import { useCallback, useEffect, useRef, useState } from 'react';
import { translateClipLines, type ClipLine } from './api';
import { koView, planKoRequest, type KoFail, type KoSettings, type KoView } from './koLines';

export type KoLine = { view: KoView; ko: string | null; reveal: () => void; retry: () => void };

// 공부 화면의 지금 줄에 붙는 한국어. 받은 번역은 이 화면이 열려 있는 동안 기억하고, 같은 줄은 다시 요청하지 않는다.
// 하루 한도를 다 쓰거나 서버가 꺼져 있으면 이 화면에서는 더 요청하지 않는다(다시 시도를 누르면 재개).
export function useKoLines(videoId: string, lines: readonly ClipLine[], index: number, settings: KoSettings): KoLine {
  const [have, setHave] = useState<ReadonlyMap<number, string>>(() => new Map());
  const [failed, setFailed] = useState<ReadonlyMap<number, KoFail>>(() => new Map());
  const [pending, setPending] = useState<ReadonlySet<number>>(() => new Set());
  const [stopped, setStopped] = useState<KoFail | null>(null);
  const [revealedId, setRevealedId] = useState<number | null>(null);

  const line = index >= 0 && index < lines.length ? lines[index] : null;
  const revealed = line !== null && revealedId === line.id;
  const plan =
    stopped === null
      ? planKoRequest({ lines, index, settings, revealed, skip: (id) => have.has(id) || failed.has(id) || pending.has(id) })
      : null;
  const planKey = plan ? `${videoId}:${plan.lines.map((l) => l.id).join(',')}` : '';
  const planRef = useRef(plan);
  planRef.current = plan;

  useEffect(() => {
    const current = planRef.current;
    if (!current) return;
    const ids = current.lines.map((l) => l.id);
    setPending((prev) => new Set([...prev, ...ids]));
    const settle = (items: { id: number; ko: string }[], fail: KoFail) => {
      const got = new Set(items.map((i) => i.id));
      setHave((prev) => new Map([...prev, ...items.map((i): [number, string] => [i.id, i.ko])]));
      setFailed((prev) => new Map([...prev, ...ids.filter((id) => !got.has(id)).map((id): [number, KoFail] => [id, fail])]));
      setPending((prev) => new Set([...prev].filter((id) => !ids.includes(id))));
    };
    translateClipLines(videoId, current).then(
      (res) => {
        if (res.unavailable) setStopped('unavailable');
        else if (res.capped) setStopped('capped');
        settle(res.items, res.unavailable ? 'unavailable' : res.capped ? 'capped' : 'error');
      },
      () => settle([], 'error'),
    );
  }, [planKey]);

  const reveal = useCallback(() => {
    if (line) setRevealedId(line.id);
  }, [line?.id]);

  const retry = useCallback(() => {
    setStopped(null);
    setFailed(new Map());
  }, []);

  const ko = line ? (have.get(line.id) ?? null) : null;
  const fail = line ? (failed.get(line.id) ?? stopped) : null;
  return { view: koView({ settings, hasLine: line !== null, revealed, ko, fail }), ko, reveal, retry };
}
