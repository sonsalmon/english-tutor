import { PeopleList, TwoPane } from '../components/PeopleList';
import { Screen, useWide } from '../components/ui';
import type { LearnerProfile } from '../lib/api';
import { PARK_ID } from '../lib/partners';
import { PersonView } from './Person';

// 홈은 사람 목록이다. 데스크톱(1024px 이상)은 오른쪽 칸에 Ms. Park 페이지를 함께 보여 준다(리다이렉트 없음).
export function Home({
  profile,
  onCall,
  onRetryProfile,
}: {
  profile: LearnerProfile | null;
  onCall: (partnerId: string) => void;
  onRetryProfile: () => void;
}) {
  const wide = useWide();
  const hint = profile?.weak_points?.[0]?.pattern;
  if (wide) {
    return (
      <Screen wide>
        <TwoPane list={<PeopleList activeId={PARK_ID} parkHint={hint} />}>
          <PersonView partnerId={PARK_ID} profile={profile} onCall={onCall} onRetryProfile={onRetryProfile} />
        </TwoPane>
      </Screen>
    );
  }
  return (
    <Screen>
      <header className="flex h-11 items-center">
        <h1 className="text-[28px] font-bold">통화</h1>
      </header>
      <div className="mt-4">
        <PeopleList activeId={null} parkHint={hint} />
      </div>
    </Screen>
  );
}
