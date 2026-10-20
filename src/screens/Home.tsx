import { Briefcase, Coffee, GraduationCap, History as HistoryIcon, MessageSquareText, Phone } from 'lucide-react';
import { CallButton, List, Portrait, QuietButton, RowLink, Screen } from '../components/ui';
import { WordText } from '../components/WordText';
import type { CallTotals, LearnerProfile } from '../lib/api';
import { go } from '../lib/router';

export function Home({
  profile,
  totals,
  onQuickCall,
  onSmallTalk,
  onRetryProfile,
}: {
  profile: LearnerProfile | null;
  totals: CallTotals | null;
  onQuickCall: () => void;
  onSmallTalk: () => void;
  onRetryProfile: () => void;
}) {
  const focus = profile?.weak_points?.[0];
  return (
    <Screen>
      <header className="flex h-11 items-center lg:hidden">
        <span className="text-sm font-semibold text-ink-soft">English Tutor</span>
      </header>

      <section className="mt-6 flex flex-col items-center text-center lg:mt-0 lg:flex-row lg:gap-6 lg:text-left">
        <Portrait size={152} />
        <div>
          <h1 className="mt-4 text-[28px] font-bold leading-tight lg:mt-0">Ms. Park</h1>
          <p className="mt-1 text-ink-soft">한국과 미국 직장을 둘 다 아는 영어 코치</p>
          <div className="mt-5 hidden lg:block">
            <CallButton onClick={onQuickCall}>
              <Phone size={22} aria-hidden />
              Ms. Park에게 전화하기
            </CallButton>
            <p className="mt-2 text-sm text-ink-soft">주제는 Ms. Park이 오늘 연습할 것에 맞춰 정해요</p>
            <div className="mt-5">
          <QuietButton onClick={onSmallTalk}>
            <Coffee size={18} aria-hidden />
            쉬는 시간 스몰토크 (5분)
          </QuietButton>
          <p className="mt-2 text-sm text-ink-soft">공부 말고 가볍게 수다만 떨어요. 점수 없이 가볍게 이야기해요.</p>
        </div>
          </div>
        </div>
      </section>

      <div className="mt-8 grid gap-4 lg:items-start lg:grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">
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
              <span className="mark">{focus.pattern}</span>
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
          <p className="leading-relaxed text-ink-soft">
            아직 기억할 기록이 없어요. 첫 통화가 끝나면 Ms. Park이 잘 틀리는 표현을 기억해요.
          </p>
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
      </div>

      <div className="mt-6 lg:hidden">
        <CallButton onClick={onQuickCall}>
          <Phone size={22} aria-hidden />
          Ms. Park에게 전화하기
        </CallButton>
        <p className="mt-2 text-center text-sm text-ink-soft">주제는 Ms. Park이 오늘 연습할 것에 맞춰 정해요</p>
        <div className="mt-5 flex flex-col items-center text-center">
          <QuietButton onClick={onSmallTalk}>
            <Coffee size={18} aria-hidden />
            쉬는 시간 스몰토크 (5분)
          </QuietButton>
          <p className="mt-2 text-sm text-ink-soft">공부 말고 가볍게 수다만 떨어요. 점수 없이 가볍게 이야기해요.</p>
        </div>
      </div>

      <section className="mt-10">
        <h2 className="mb-3 font-semibold">다른 방법으로 연습하기</h2>
        <List columns={2}>
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
