import { useEffect, useState } from 'react';
import { List, RowLink, Screen, TopBar } from '../components/ui';
import { TutoringBlocks } from '../components/TutoringBlocks';
import { getCall, getCalls, type CallDetail, type CallSummary, type CallTotals } from '../lib/api';
import { go } from '../lib/router';

type Loaded<T> = { data: T | null; error: string | null };

function formatWhen(startedAt: string): string {
  const [date, time] = startedAt.split(' ');
  const [, month, day] = date.split('-').map(Number);
  return `${month}월 ${day}일 ${time}`;
}

function formatDuration(sec: number): string {
  const minutes = Math.floor(sec / 60);
  const seconds = sec % 60;
  return minutes > 0 ? `${minutes}분 ${seconds}초` : `${seconds}초`;
}

function useLoaded<T>(load: (signal: AbortSignal) => Promise<T>, key: string): Loaded<T> {
  const [state, setState] = useState<Loaded<T> & { key: string }>({ data: null, error: null, key: '' });
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => setState({ data, error: null, key }),
      (e: unknown) => {
        if (!controller.signal.aborted) setState({ data: null, error: e instanceof Error ? e.message : '불러오지 못했어요.', key });
      },
    );
    return () => controller.abort();
    // key가 바뀔 때만 다시 불러온다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state.key === key ? state : { data: null, error: null };
}

function Totals({ totals }: { totals: CallTotals }) {
  const items = [
    { label: '통화', value: totals.calls },
    { label: '분', value: totals.minutes },
    { label: '날', value: totals.days },
  ];
  return (
    <dl className="grid grid-cols-3 divide-x divide-line rounded-2xl border border-line bg-surface py-4 text-center">
      {items.map((item) => (
        <div key={item.label} className="flex flex-col-reverse gap-1">
          <dt className="text-sm text-ink-soft">{item.label}</dt>
          <dd className="text-[28px] leading-none font-bold">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function WeekLine({ week }: { week: number }) {
  return (
    <p className="mt-3 text-center text-ink-soft">
      {week > 0 ? `이번 주에 ${week}번 통화했어요.` : '이번 주에는 아직 통화하지 않았어요.'}
    </p>
  );
}

function SummaryChip() {
  return <span className="shrink-0 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">요약 있음</span>;
}

function CallList() {
  const { data, error } = useLoaded((signal) => getCalls(50, signal), 'list');
  return (
    <Screen>
      <TopBar title="통화 기록" onBack={() => go('home')} />
      {error ? (
        <p className="text-ink-soft" role="alert">{error}</p>
      ) : !data ? (
        <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
      ) : (
        <>
          <Totals totals={data.totals} />
          <WeekLine week={data.totals.week} />
          <div className="mt-6">
            {data.calls.length === 0 ? (
              <p className="leading-relaxed text-ink-soft">아직 저장된 통화가 없어요. 첫 통화가 끝나면 여기에 쌓여요.</p>
            ) : (
              <List>
                {data.calls.map((call: CallSummary) => (
                  <RowLink
                    key={call.stem}
                    title={call.mission}
                    desc={`${formatWhen(call.started_at)}, ${formatDuration(call.duration_sec)}`}
                    trailing={call.has_tutoring ? <SummaryChip /> : undefined}
                    onClick={() => go('history', false, call.stem)}
                  />
                ))}
              </List>
            )}
          </div>
        </>
      )}
    </Screen>
  );
}

function CallDetailView({ stem }: { stem: string }) {
  const { data, error } = useLoaded<CallDetail>((signal) => getCall(stem, signal), stem);
  return (
    <Screen>
      <TopBar title="통화 기록" onBack={() => go('history')} />
      {error ? (
        <p className="text-ink-soft" role="alert">{error}</p>
      ) : !data ? (
        <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
      ) : (
        <>
          <header>
            <h2 className="text-[22px] leading-snug font-bold">{data.call.mission}</h2>
            <p className="mt-1 text-ink-soft">
              {formatWhen(data.call.started_at)}, {formatDuration(data.call.duration_sec)}
              {data.call.completed ? '' : ', 중간에 마쳤어요'}
            </p>
          </header>
          {data.tutoring ? (
            <TutoringBlocks tutoring={data.tutoring} isTeachback={data.call.kind === 'teachback'} />
          ) : (
            <p className="mt-8 leading-relaxed text-ink-soft">이 통화는 저장된 요약이 없어요.</p>
          )}
        </>
      )}
    </Screen>
  );
}

export function CallHistory({ stem }: { stem: string | null }) {
  return stem ? <CallDetailView stem={stem} /> : <CallList />;
}
