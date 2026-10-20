import { useEffect, useState } from 'react';
import { List, RowLink, Screen, TopBar, useWide } from '../components/ui';
import { ClipList } from '../components/ClipList';
import { CultureNotes } from '../components/CultureNotes';
import { FriendMessage } from '../components/FriendMessage';
import { ThinkingGaps } from '../components/ThinkingGaps';
import { CostLine, TutoringBlocks } from '../components/TutoringBlocks';
import { ReplayButton, TranscriptView } from '../components/TranscriptView';
import { WordText } from '../components/WordText';
import { formatUsdShort, getCall, getCalls, type CallDetail, type CallSummary, type CallTotals } from '../lib/api';
import { latencyText, type CallLatency } from '../lib/latency';
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
      {week > 0 ? `최근 7일 동안 ${week}번 통화했어요.` : '최근 7일 동안은 통화하지 않았어요.'}
    </p>
  );
}

function SummaryChip() {
  return <span className="shrink-0 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">요약 있음</span>;
}

function RowMeta({ call }: { call: CallSummary }) {
  const total = call.cost?.total;
  if (!call.has_tutoring && total == null) return null;
  return (
    <span className="flex shrink-0 flex-col items-end gap-1">
      {call.has_tutoring && <SummaryChip />}
      {total != null && <span className="text-xs text-ink-soft">예상 {formatUsdShort(total)}</span>}
    </span>
  );
}

type Filter = 'all' | 'study' | 'smalltalk';
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: 'study', label: '공부' },
  { id: 'smalltalk', label: '스몰토크' },
];

function FilterRow({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  return (
    <div role="group" aria-label="통화 종류" className="mt-6 flex gap-2">
      {FILTERS.map((f) => (
        <button
          key={f.id}
          type="button"
          aria-pressed={value === f.id}
          onClick={() => onChange(f.id)}
          className={`min-h-11 rounded-full border px-4 font-semibold ${
            value === f.id ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-ink'
          }`}
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}

function CallListBody({ activeStem }: { activeStem: string | null }) {
  const { data, error } = useLoaded((signal) => getCalls(50, signal), 'list');
  const [filter, setFilter] = useState<Filter>('all');
  const shown = data ? data.calls.filter((c) => (filter === 'all' ? true : filter === 'smalltalk' ? c.kind === 'smalltalk' : c.kind !== 'smalltalk')) : [];
  return (
    <>
      {error ? (
        <p className="text-ink-soft" role="alert">{error}</p>
      ) : !data ? (
        <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
      ) : (
        <>
          <Totals totals={data.totals} />
          {data.totals.calls > 0 && <WeekLine week={data.totals.week} />}
          <FilterRow value={filter} onChange={setFilter} />
          <div className="mt-4">
            {shown.length === 0 ? (
              <p className="leading-relaxed text-ink-soft">{data.calls.length === 0 ? '아직 저장된 통화가 없어요. 첫 통화가 끝나면 여기에 쌓여요.' : '이 종류의 통화는 아직 없어요.'}</p>
            ) : (
              <List>
                {shown.map((call: CallSummary) => (
                  <RowLink
                    key={call.stem}
                    title={call.mission}
                    desc={`${formatWhen(call.started_at)}, ${formatDuration(call.duration_sec)}`}
                    trailing={<RowMeta call={call} />}
                    active={call.stem === activeStem}
                    onClick={() => go('history', false, call.stem)}
                  />
                ))}
              </List>
            )}
          </div>
        </>
      )}
    </>
  );
}

function CallDetailBody({ stem }: { stem: string }) {
  const { data, error } = useLoaded<CallDetail>((signal) => getCall(stem, signal), stem);
  return (
    <>
      {error ? (
        <p className="text-ink-soft" role="alert">{error}</p>
      ) : !data ? (
        <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
      ) : (
        <>
          <header>
            <h2 className="text-[22px] leading-snug font-bold">
              <WordText text={data.call.mission} />
            </h2>
            <p className="mt-1 text-ink-soft">
              {formatWhen(data.call.started_at)}, {formatDuration(data.call.duration_sec)}
              {data.call.completed ? '' : ', 중간에 마쳤어요'}
            </p>
            {latencyText((data.call as { latency?: CallLatency | null }).latency) && (
              <p className="mt-1 text-sm text-ink-soft">{latencyText((data.call as { latency?: CallLatency | null }).latency)}</p>
            )}
            <CostLine cost={data.call.cost ?? data.tutoring?.cost} className="mt-1" />
          </header>
          {data.tutoring ? (
            <>
              <FriendMessage message={data.tutoring.friend_message} partnerId={data.call.partner} />
              <TutoringBlocks tutoring={data.tutoring} isTeachback={data.call.kind === 'teachback'} />
              <ThinkingGaps gaps={data.tutoring.thinking_gaps} />
            </>
          ) : (
            <p className="mt-8 leading-relaxed text-ink-soft">이 통화는 저장된 요약이 없어요.</p>
          )}
          <CultureNotes stem={stem} />
          <TranscriptView turns={data.transcript} verbatim={data.verbatim} voice={data.call.voice} />
          <ClipList stem={stem} />
          <ReplayButton stem={stem} />
        </>
      )}
    </>
  );
}

export function CallHistory({ stem }: { stem: string | null }) {
  const wide = useWide();
  if (wide) {
    return (
      <Screen wide>
        <TopBar title="통화 기록" onBack={() => go('home')} />
        <div className="grid grid-cols-[320px_minmax(0,1fr)] items-start gap-10">
          <div>
            <CallListBody activeStem={stem} />
          </div>
          <div className="min-w-0">
            {stem ? (
              <CallDetailBody stem={stem} />
            ) : (
              <p className="leading-relaxed text-ink-soft">왼쪽에서 통화를 고르면 요약이 여기에 나와요.</p>
            )}
          </div>
        </div>
      </Screen>
    );
  }
  return (
    <Screen>
      <TopBar title="통화 기록" onBack={() => go(stem ? 'history' : 'home')} />
      {stem ? <CallDetailBody stem={stem} /> : <CallListBody activeStem={null} />}
    </Screen>
  );
}
