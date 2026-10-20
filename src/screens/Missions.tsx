import missionsData from '../data/missions.json';
import { List, RowLink, Screen, TopBar } from '../components/ui';
import type { Mission } from '../lib/instructions';
import { go } from '../lib/router';

const LEVELS: Record<string, { label: string; className: string }> = {
  Easy: { label: '쉬움', className: 'bg-call/10 text-call-press' },
  Medium: { label: '보통', className: 'bg-marker/50 text-ink' },
  Hard: { label: '어려움', className: 'bg-end/10 text-end-press' },
};

const MISSIONS = (missionsData as Mission[]).filter((m) => m.type !== 'teachback');

export function Missions({ onPick }: { onPick: (mission: Mission) => void }) {
  return (
    <Screen>
      <TopBar title="상황 역할극" onBack={() => go('home')} />
      <p className="mb-4 leading-relaxed text-ink-soft">
        장면을 고르면 Ms. Park이 그 역할로 통화해요. 끝나면 쉬운 영어로 짧게 피드백해요.
      </p>
      <List>
        {MISSIONS.map((m) => {
          const level = LEVELS[m.difficulty] ?? LEVELS.Medium;
          return (
            <RowLink
              key={m.id}
              title={m.title}
              desc={m.desc.replace(/^Your goal:\s*/i, '')}
              onClick={() => onPick(m)}
              trailing={
                <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${level.className}`}>{level.label}</span>
              }
            />
          );
        })}
      </List>
    </Screen>
  );
}
