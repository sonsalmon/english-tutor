import { WifiOff } from 'lucide-react';
import { PeopleList, TwoPane } from '../components/PeopleList';
import { Screen, useWide } from '../components/ui';
import type { LearnerProfile } from '../lib/api';
import { PARK_ID } from '../lib/partners';
import { useOnline } from '../lib/useOnline';
import { PersonView } from './Person';

function OfflineBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="mb-3 flex items-center gap-3 rounded-2xl border border-end/40 bg-end/10 py-2 pr-2 pl-4 text-ink">
      <WifiOff size={20} aria-hidden className="shrink-0" />
      <p className="flex-1 text-sm font-medium">서버에 연결되지 않았어요. Tailscale이 켜져 있는지 확인해 주세요.</p>
      <button type="button" onClick={onRetry} className="min-h-11 shrink-0 rounded-full px-3 text-sm font-bold hover:bg-end/10">
        다시 확인
      </button>
    </div>
  );
}

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
  const { reachable, recheck } = useOnline();
  const hint = profile?.weak_points?.[0]?.pattern;
  if (wide) {
    return (
      <Screen wide>
        {!reachable && <OfflineBanner onRetry={recheck} />}
        <TwoPane list={<PeopleList activeId={PARK_ID} parkHint={hint} />}>
          <PersonView partnerId={PARK_ID} profile={profile} onCall={onCall} onRetryProfile={onRetryProfile} />
        </TwoPane>
      </Screen>
    );
  }
  return (
    <Screen>
      {!reachable && <OfflineBanner onRetry={recheck} />}
      <header className="flex h-11 items-center">
        <h1 className="text-[28px] font-bold">통화</h1>
      </header>
      <div className="mt-4">
        <PeopleList activeId={null} parkHint={hint} />
      </div>
    </Screen>
  );
}
