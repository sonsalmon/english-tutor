import { Briefcase, GraduationCap, History as HistoryIcon, MessageSquareText, Phone } from 'lucide-react';
import { CallButton, List, Portrait, RowLink, Screen } from '../components/ui';
import type { CallTotals, LearnerProfile } from '../lib/api';
import { go } from '../lib/router';

export function Home({ profile, totals, onQuickCall }: { profile: LearnerProfile | null; totals: CallTotals | null; onQuickCall: () => void }) {
  const focus = profile?.weak_points?.[0];
  return (
    <Screen>
      <header className="flex h-11 items-center">
        <span className="text-sm font-semibold text-ink-soft">English Tutor</span>
      </header>

      <section className="mt-6 flex flex-col items-center text-center">
        <Portrait size={152} />
        <h1 className="mt-4 text-[28px] font-bold leading-tight">Ms. Park</h1>
        <p className="mt-1 text-ink-soft">한국과 미국 직장을 둘 다 아는 영어 코치</p>
      </section>

      <section className="mt-8 rounded-2xl border border-line bg-surface p-5" aria-live="polite">
        {profile === null ? (
          <p className="text-ink-soft">지난 통화 기록을 불러오는 중이에요.</p>
        ) : focus ? (
          <>
            <h2 className="text-sm font-semibold text-ink-soft">오늘 연습할 것</h2>
            <p className="mt-2 text-xl font-bold leading-snug">
              <span className="mark">{focus.pattern}</span>
            </p>
            {focus.example && <p className="mt-2 text-ink-soft">“{focus.example}”</p>}
            {profile.next_goal && <p className="mt-3 border-t border-line pt-3 text-[15px] leading-relaxed">{profile.next_goal}</p>}
          </>
        ) : (
          <p className="leading-relaxed text-ink-soft">
            아직 기억할 기록이 없어요. 첫 통화가 끝나면 Ms. Park이 잘 틀리는 표현을 기억해요.
          </p>
        )}
      </section>

      <div className="mt-6">
        <CallButton onClick={onQuickCall}>
          <Phone size={22} aria-hidden />
          Ms. Park에게 전화하기
        </CallButton>
        <p className="mt-2 text-center text-sm text-ink-soft">주제는 Ms. Park이 오늘 연습할 것에 맞춰 정해요</p>
      </div>

      <section className="mt-10">
        <h2 className="mb-3 font-semibold">다른 방법으로 연습하기</h2>
        <List>
          <RowLink icon={Briefcase} title="상황 역할극" desc="미국 회사와 생활 장면 12개" onClick={() => go('missions')} />
          <RowLink icon={MessageSquareText} title="주제 정해서 대화" desc="글이나 메모를 붙여 넣고 이야기해요" onClick={() => go('topic')} />
          <RowLink icon={GraduationCap} title="가르치며 배우기" desc="오늘 공부한 내용을 영어로 설명해요" onClick={() => go('teachback')} />
          <RowLink
            icon={HistoryIcon}
            title="통화 기록"
            desc={totals && totals.calls > 0 ? `지금까지 ${totals.calls}번, ${totals.minutes}분, ${totals.days}일` : '지난 통화와 요약을 다시 봐요'}
            onClick={() => go('history')}
          />
        </List>
      </section>
    </Screen>
  );
}
