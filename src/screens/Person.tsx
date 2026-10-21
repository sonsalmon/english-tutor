import { Briefcase, ChevronLeft, ChevronRight, GraduationCap, MessageCircle, MessageSquareText, Phone } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Avatar } from '../components/Avatar';
import { FriendMemory, type MemoryState } from '../components/FriendMemory';
import { SummaryBadge } from '../components/SummaryState';
import { PeopleList, TwoPane } from '../components/PeopleList';
import { CallButton, List, QuietButton, RowLink, Screen, useWide } from '../components/ui';
import { WordText } from '../components/WordText';
import { getPartnerMemory, type CallSummary, type LearnerProfile, type PartnerMemory } from '../lib/api';
import { getPersonCalls } from '../lib/apiPeople';
import { formatShortDuration, formatWhen } from '../lib/callFormat';
import { PARK_ID, isPark, partnerMeta, type Partner } from '../lib/partners';
import { pronSummaryOf, type PronWeak } from '../lib/pron';
import { go } from '../lib/router';
import { useSummaryPolling } from '../lib/useSummaryPolling';
import { useSwipe } from '../lib/swipe';
import { visiblePartners } from '../lib/visibility';

const SWIPE_HINT_KEY = 'english-tutor.swipe-hint';
const SWIPE_HINT_MAX = 3;

function weakText(w: PronWeak): string {
  if (w.worst && w.worst.total > 0) {
    const { target, other, as_other, unclear, total } = w.worst;
    if (as_other > 0) return `${target} → ${other} ${as_other}/${total}` + (unclear > 0 ? ` · 알아듣기 어려움 ${unclear}` : '');
    return `${target}: 알아듣기 어려움 ${unclear}/${total}`;
  }
  const parts: string[] = [];
  if (w.as_other > 0) parts.push(`다르게 들려요 ${w.as_other}/${w.total}`);
  if (w.unclear > 0) parts.push(`불분명해요 ${w.unclear}/${w.total}`);
  return parts.join(', ');
}

// 사람 페이지를 폰 화면에서 처음 3번 열 때만 스와이프 안내를 보인다. 데스크톱(lg 이상)에서는 안내가 숨겨지므로 횟수를 세지 않는다.
function SwipeHint() {
  const [show, setShow] = useState(false);
  const counted = useRef(false);
  useEffect(() => {
    if (counted.current || !window.matchMedia('(max-width: 1023px)').matches) return;
    counted.current = true;
    try {
      const seen = Number(window.localStorage.getItem(SWIPE_HINT_KEY)) || 0;
      if (seen >= SWIPE_HINT_MAX) return;
      window.localStorage.setItem(SWIPE_HINT_KEY, String(seen + 1));
      setShow(true);
    } catch {
      // 저장소를 못 쓰면 안내를 보이지 않는다.
    }
  }, []);
  if (!show) return null;
  return <p className="mt-3 text-center text-sm text-ink-soft lg:hidden">오른쪽으로 밀면 채팅이 열려요</p>;
}

function ParkCards({ profile, onRetryProfile }: { profile: LearnerProfile | null; onRetryProfile: () => void }) {
  const focus = profile?.weak_points?.[0];
  const pron = pronSummaryOf(profile);
  return (
    <div className="mt-8 grid gap-4">
      <section className="rounded-2xl border border-line bg-surface p-5" aria-live="polite">
        {profile === null ? (
          <p className="text-ink-soft">지난 통화 기록을 불러오는 중이에요.</p>
        ) : profile.load_failed ? (
          <>
            <p className="leading-relaxed text-ink-soft">지난 기록을 불러오지 못했어요.</p>
            <div className="mt-3">
              <QuietButton onClick={onRetryProfile}>다시 불러오기</QuietButton>
            </div>
          </>
        ) : focus ? (
          <>
            <h2 className="text-sm font-semibold text-ink-soft">오늘 연습할 것</h2>
            <p className="mt-2 text-xl font-bold leading-snug">
              <span className="mark">
                <WordText text={focus.pattern} />
              </span>
            </p>
            {focus.example && (
              <p className="mt-2 text-ink-soft">
                “<WordText text={focus.example} />”
              </p>
            )}
            {profile.next_goal && (
              <p className="mt-3 border-t border-line pt-3 text-[15px] leading-relaxed">
                <WordText text={profile.next_goal} />
              </p>
            )}
          </>
        ) : (
          <p className="leading-relaxed text-ink-soft">아직 기억할 기록이 없어요. 첫 통화가 끝나면 Ms. Park이 잘 틀리는 표현을 기억해요.</p>
        )}
      </section>

      {profile && profile.practice_words.length > 0 && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink-soft">읽다가 찾아본 단어</h2>
          <p className="mt-1 text-[15px] leading-relaxed">Ms. Park이 통화에서 이 단어를 써 볼 기회를 만들어요.</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {profile.practice_words.map((w) => (
              <li key={w.lemma} className="rounded-xl bg-paper px-3 py-2">
                <span className="font-semibold">
                  <WordText text={w.lemma} />
                </span>
                {w.gloss && <span className="ml-1.5 text-sm text-ink-soft">{w.gloss}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {profile && !profile.load_failed && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold text-ink-soft">발음</h2>
          {pron && pron.weak.length > 0 ? (
            <>
              <p className="mt-1 text-[15px] leading-relaxed">{pron.date} 진단에서 다르게 들린 소리예요.</p>
              <ul className="mt-3 space-y-2">
                {pron.weak.slice(0, 3).map((w) => (
                  <li key={w.label} className="flex items-baseline justify-between gap-3">
                    <span className="font-semibold">
                      <WordText text={w.label} />
                    </span>
                    <span className="text-sm text-ink-soft">{weakText(w)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : pron ? (
            <p className="mt-1 leading-relaxed text-ink-soft">{pron.date} 진단에서는 다르게 들린 소리가 없었어요.</p>
          ) : (
            <p className="mt-1 leading-relaxed text-ink-soft">내 발음 습관부터 재 봐요. 문장을 읽으면 어떻게 들리는지 알려 줘요. 5분쯤 걸려요.</p>
          )}
          <div className="mt-4">
            <QuietButton onClick={() => go('pron')}>{pron ? '자세히 보기' : '발음 진단하기'}</QuietButton>
          </div>
        </section>
      )}
    </div>
  );
}

function CallHistoryList({ partnerId }: { partnerId: string }) {
  const [calls, setCalls] = useState<CallSummary[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setCalls(null);
    setFailed(false);
    const controller = new AbortController();
    getPersonCalls(partnerId, 50, controller.signal).then(setCalls, () => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [partnerId]);

  const running = calls?.some((c) => c.summary === 'running') ?? false;
  useSummaryPolling(
    running,
    async (signal) => {
      setCalls(await getPersonCalls(partnerId, 50, signal));
    },
    partnerId,
  );

  const park = partnerId === PARK_ID;
  return (
    <section className="mt-8">
      <h2 className="mb-3 font-semibold">통화 내역</h2>
      {failed ? (
        <p className="text-ink-soft" role="alert">
          통화 내역을 불러오지 못했어요.
        </p>
      ) : calls === null ? (
        <p className="text-ink-soft">통화 내역을 불러오는 중이에요.</p>
      ) : calls.length === 0 ? (
        <p className="leading-relaxed text-ink-soft">아직 통화한 적이 없어요. 전화하기를 누르면 첫 통화가 시작돼요.</p>
      ) : (
        <List>
          {calls.map((call) => (
            <RowLink
              key={call.stem}
              title={`${formatWhen(call.started_at)} · ${formatShortDuration(call.duration_sec)}`}
              desc={park ? call.mission : undefined}
              trailing={call.has_tutoring ? <span className="shrink-0 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold">요약 있음</span> : <SummaryBadge status={call.summary} />}
              onClick={() => go('log', false, call.stem)}
            />
          ))}
        </List>
      )}
    </section>
  );
}

// 친구가 기억하는 것은 접어 두고, 열 때만 불러온다(통화 화면에 있던 카드를 옮겨 왔다).
function Memory({ partner }: { partner: Partner }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<MemoryState>({ status: 'loading' });

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setState({ status: 'loading' });
    getPartnerMemory(partner.id, controller.signal).then(
      (memory) => setState({ status: 'ready', memory }),
      () => {
        if (!controller.signal.aborted) setState({ status: 'failed' });
      },
    );
    return () => controller.abort();
  }, [open, partner.id]);

  const change = (memory: PartnerMemory | null) => setState({ status: 'ready', memory });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={false}
        className="mt-8 flex min-h-14 w-full items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-4 text-left font-semibold hover:bg-paper"
      >
        {partner.name}의 기억
        <ChevronRight size={20} className="shrink-0 text-ink-soft" aria-hidden />
      </button>
    );
  }
  return (
    <div className="mt-3">
      <FriendMemory partnerId={partner.id} name={partner.name} state={state} onChange={change} />
      <div className="mt-3">
        <QuietButton onClick={() => setOpen(false)}>기억 접기</QuietButton>
      </div>
    </div>
  );
}

export function PersonView({
  partnerId,
  profile,
  onCall,
  onRetryProfile,
}: {
  partnerId: string;
  profile: LearnerProfile | null;
  onCall: (partnerId: string) => void;
  onRetryProfile: () => void;
}) {
  const partner = visiblePartners().find((p) => p.id === partnerId);
  const swipe = useSwipe({ onRight: () => go('chat', false, partnerId) });
  if (!partner) return null;
  const park = isPark(partner);

  return (
    <div
      data-person={partner.id}
      className="min-h-[60dvh] flex-1 lg:flex-none"
      {...(park ? {} : swipe.handlers)}
      style={park ? undefined : swipe.style}
    >
      <section className="flex flex-col items-center text-center lg:flex-row lg:gap-6 lg:text-left">
        <Avatar partner={partner} size={96} />
        <div className="mt-3 lg:mt-0">
          <h1 className="text-[28px] leading-tight font-bold">{partner.name}</h1>
          <p className="mt-1 text-ink-soft">{park ? '한국계 미국인 영어 코치' : partnerMeta(partner)}</p>
        </div>
      </section>

      <div className="mt-6 flex gap-3 lg:justify-start">
        <div className={`min-w-0 ${park ? 'flex-1 lg:flex-none' : 'flex-[2] lg:flex-none'}`}>
          <CallButton onClick={() => onCall(partner.id)}>
            <Phone size={22} aria-hidden />
            {park ? 'Ms. Park에게 전화하기' : '전화하기'}
          </CallButton>
        </div>
        {!park && (
          <div className="min-w-0 flex-1 lg:flex-none">
            <QuietButton onClick={() => go('chat', false, partner.id)}>
              <MessageCircle size={18} aria-hidden />
              채팅
            </QuietButton>
          </div>
        )}
      </div>
      {park ? (
        <p className="mt-2 text-center text-sm text-ink-soft lg:text-left">자유 대화예요. 주제는 오늘 연습할 것에 맞춰 정해요.</p>
      ) : (
        <SwipeHint />
      )}

      {park && (
        <>
          <section className="mt-8">
            <h2 className="mb-3 font-semibold">공부 방법</h2>
            <List>
              <RowLink icon={MessageSquareText} title="자유 대화" desc="주제 정하기" onClick={() => go('topic')} />
              <RowLink icon={Briefcase} title="상황 역할극" desc="미국 회사와 생활 장면 12개" onClick={() => go('missions')} />
              <RowLink icon={GraduationCap} title="가르치며 배우기" desc="오늘 공부한 내용을 영어로 설명해요" onClick={() => go('teachback')} />
            </List>
          </section>
          <ParkCards profile={profile} onRetryProfile={onRetryProfile} />
        </>
      )}

      <CallHistoryList partnerId={partner.id} />
      {!park && <Memory partner={partner} />}
    </div>
  );
}

// #/person/<id>: 폰은 전체 화면, 데스크톱은 사람 목록 옆 오른쪽 칸. 모르거나 숨긴 사람이면 홈으로 보낸다.
export function Person({
  partnerId,
  profile,
  onCall,
  onRetryProfile,
}: {
  partnerId: string | null;
  profile: LearnerProfile | null;
  onCall: (partnerId: string) => void;
  onRetryProfile: () => void;
}) {
  const wide = useWide();
  const partner = partnerId ? visiblePartners().find((p) => p.id === partnerId) : undefined;
  useEffect(() => {
    if (!partner) go('home', true);
  }, [partner]);
  if (!partner) return null;
  const hint = profile?.weak_points?.[0]?.pattern;
  const view = <PersonView partnerId={partner.id} profile={profile} onCall={onCall} onRetryProfile={onRetryProfile} />;
  if (wide) {
    return (
      <Screen wide>
        <TwoPane list={<PeopleList activeId={partner.id} parkHint={hint} />}>{view}</TwoPane>
      </Screen>
    );
  }
  return (
    <Screen>
      <header className="-ml-2 mb-2 flex items-center">
        <button type="button" onClick={() => go('home')} aria-label="뒤로" className="grid size-11 place-items-center rounded-full text-ink hover:bg-line/60">
          <ChevronLeft size={24} aria-hidden />
        </button>
      </header>
      {view}
    </Screen>
  );
}
