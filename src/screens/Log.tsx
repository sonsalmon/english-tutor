import { ChevronLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { ClipList } from '../components/ClipList';
import { CultureNotes } from '../components/CultureNotes';
import { FriendMessage } from '../components/FriendMessage';
import { PeopleList, TwoPane } from '../components/PeopleList';
import { SummaryBadge, SummaryPlaceholder } from '../components/SummaryState';
import { ThinkingGaps } from '../components/ThinkingGaps';
import { CostLine, TutoringBlocks } from '../components/TutoringBlocks';
import { ReplayButton, TranscriptView } from '../components/TranscriptView';
import { List, RowLink, Screen, TopBar, useWide } from '../components/ui';
import { WordText } from '../components/WordText';
import { formatUsdShort, getCall, getCalls, startSummary, type CallDetail, type CallSummary, type CallTotals } from '../lib/api';
import { formatDuration, formatWhen } from '../lib/callFormat';
import { latencyText } from '../lib/latency';
import { useFinishReview } from '../lib/review';
import { PARK_ID, isPark, partnerById } from '../lib/partners';
import { go } from '../lib/router';
import { anyRunning } from '../lib/summaryStatus';
import { useSummaryPolling } from '../lib/useSummaryPolling';

type Loaded<T> = { data: T | null; error: string | null };

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
  const progress = call.summary === 'running' || call.summary === 'failed';
  if (!call.has_tutoring && total == null && !progress) return null;
  return (
    <span className="flex shrink-0 flex-col items-end gap-1">
      {call.has_tutoring ? <SummaryChip /> : <SummaryBadge status={call.summary} />}
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

function CallListBody() {
  const { data: loaded, error } = useLoaded((signal) => getCalls(50, signal), 'list');
  const [fresh, setFresh] = useState<Awaited<ReturnType<typeof getCalls>> | null>(null);
  const data = fresh ?? loaded;
  useSummaryPolling(!!data && anyRunning(data.calls), async (signal) => setFresh(await getCalls(50, signal)), 'list');
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
                    onClick={() => go('log', false, call.stem)}
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

type DetailTab = 'summary' | 'transcript' | 'clips';
const TABS: { id: DetailTab; label: string }[] = [
  { id: 'summary', label: '요약' },
  { id: 'transcript', label: '전문' },
  { id: 'clips', label: '클립' },
];

function DetailTabs({ value, onChange }: { value: DetailTab; onChange: (tab: DetailTab) => void }) {
  return (
    <div role="tablist" aria-label="통화 내역 보기" className="mt-5 grid grid-cols-3 gap-1 rounded-full border border-line bg-surface p-1">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`log-tab-${tab.id}`}
          aria-selected={value === tab.id}
          aria-controls="log-panel"
          onClick={() => onChange(tab.id)}
          className={`min-h-11 rounded-full px-4 font-semibold ${value === tab.id ? 'bg-ink text-white' : 'text-ink hover:bg-paper'}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function CallDetailBody({ data, stem, onStartSummary }: { data: CallDetail; stem: string; onStartSummary: () => Promise<void> }) {
  const [tab, setTab] = useState<DetailTab>('summary');
  const [starting, setStarting] = useState(false);
  const [startFailed, setStartFailed] = useState(false);
  const startNow = async () => {
    setStarting(true);
    setStartFailed(false);
    try {
      await onStartSummary();
    } catch {
      setStartFailed(true);
    } finally {
      setStarting(false);
    }
  };
  // 탭을 옮겨도 화면이 열려 있는 동안은 검토가 끝난 것이 아니다(요약 탭의 블록이 언마운트되어도 유지).
  // 요약이 아직 없으면(정리하는 중) 보여 준 게 없으니 검토 완료로 치지 않는다.
  useFinishReview(data.tutoring ? stem : null);
  const latency = latencyText(data.call.latency);
  const partner = partnerById(data.call.partner);
  const hasTranscript = data.transcript.length > 0 || !!data.verbatim;
  return (
    <>
      <header>
        <h2 className="text-[22px] leading-snug font-bold">{isPark(partner) ? <WordText text={data.call.mission} /> : `${partner.name} 통화`}</h2>
        <p className="mt-1 text-ink-soft">
          {formatWhen(data.call.started_at)} · {formatDuration(data.call.duration_sec)}
          {data.call.completed ? '' : ' · 중간에 마쳤어요'}
        </p>
        {latency && <p className="mt-1 text-sm text-ink-soft">{latency}</p>}
        <CostLine cost={data.call.cost ?? data.tutoring?.cost} className="mt-1" />
      </header>
      <DetailTabs value={tab} onChange={setTab} />
      <div role="tabpanel" id="log-panel" aria-labelledby={`log-tab-${tab}`}>
        {tab === 'summary' && (
          <>
            {data.tutoring ? (
              <>
                <FriendMessage message={data.tutoring.friend_message} partnerId={data.call.partner} />
                <TutoringBlocks tutoring={data.tutoring} isTeachback={data.call.kind === 'teachback'} stem={stem} />
                <ThinkingGaps tutoring={data.tutoring} stem={stem} />
              </>
            ) : (
              <SummaryPlaceholder status={data.call.summary} onStart={startNow} starting={starting} startFailed={startFailed} />
            )}
            <CultureNotes stem={stem} />
          </>
        )}
        {tab === 'transcript' &&
          (hasTranscript ? (
            <TranscriptView turns={data.transcript} verbatim={data.verbatim} voice={data.call.voice} />
          ) : (
            <p className="mt-8 leading-relaxed text-ink-soft">이 통화는 저장된 전문이 없어요.</p>
          ))}
        {tab === 'clips' && (
          <>
            <ClipList stem={stem} />
            <ReplayButton stem={stem} />
          </>
        )}
      </div>
    </>
  );
}

function LogDetailScreen({ stem, parkHint }: { stem: string; parkHint?: string }) {
  const wide = useWide();
  const { data: loaded, error } = useLoaded<CallDetail>((signal) => getCall(stem, signal), stem);
  const [fresh, setFresh] = useState<{ stem: string; detail: CallDetail } | null>(null);
  const data = fresh && fresh.stem === stem ? fresh.detail : loaded;
  const refresh = async (signal?: AbortSignal) => {
    setFresh({ stem, detail: await getCall(stem, signal) });
  };
  useSummaryPolling(data?.call.summary === 'running', refresh, stem);
  const startNow = async () => {
    await startSummary(stem);
    await refresh();
  };
  const partnerId = data ? (data.call.partner ?? PARK_ID) : null;
  const backTo = partnerId ?? PARK_ID;
  const body = error ? (
    <p className="text-ink-soft" role="alert">
      {error}
    </p>
  ) : !data ? (
    <p className="text-ink-soft">통화 기록을 불러오는 중이에요.</p>
  ) : (
    <CallDetailBody key={stem} data={data} stem={stem} onStartSummary={startNow} />
  );

  if (wide) {
    return (
      <Screen wide>
        <TwoPane list={<PeopleList activeId={partnerId} parkHint={parkHint} />}>
          <button
            type="button"
            onClick={() => go('person', false, backTo)}
            className="-ml-2 mb-3 flex min-h-11 items-center gap-1 rounded-full px-2 font-semibold text-ink hover:bg-line/60"
          >
            <ChevronLeft size={20} aria-hidden />
            {partnerById(backTo).name}
          </button>
          {body}
        </TwoPane>
      </Screen>
    );
  }
  return (
    <Screen>
      <TopBar title="통화 내역" onBack={() => go('person', false, backTo)} />
      {body}
    </Screen>
  );
}

// #/log: 전체 통화 기록. #/log/<stem>: 통화 내역 상세(폰은 전체 화면, 데스크톱은 사람 목록 옆 오른쪽 칸).
export function Log({ stem, parkHint }: { stem: string | null; parkHint?: string }) {
  if (!stem) {
    return (
      <Screen>
        <TopBar title="전체 통화 기록" onBack={() => go('settings')} />
        <CallListBody />
      </Screen>
    );
  }
  return <LogDetailScreen stem={stem} parkHint={parkHint} />;
}
