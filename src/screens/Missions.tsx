import missionsData from '../data/missions.json';
import { List, Screen, TopBar } from '../components/ui';
import { WordText } from '../components/WordText';
import { ChevronRight } from 'lucide-react';
import type { Mission } from '../lib/instructions';
import { PARK_ID } from '../lib/partners';
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
      <TopBar title="상황 역할극" onBack={() => go('person', false, PARK_ID)} />
      <p className="mb-4 leading-relaxed text-ink-soft">
        장면을 고르면 Ms. Park이 그 역할로 통화해요. 끝나면 쉬운 영어로 짧게 피드백해요.
      </p>
      <List>
        {MISSIONS.map((m) => {
          const level = LEVELS[m.difficulty] ?? LEVELS.Medium;
          return (
            <div key={m.id} className="relative hover:bg-paper">
              <button type="button" onClick={() => onPick(m)} aria-label={`${m.title} 시작`} className="absolute inset-0 w-full" />
              <div className="pointer-events-none relative flex items-center gap-4 px-4 py-4">
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">
                    <WordText text={m.title} />
                  </span>
                  <span className="mt-0.5 block text-sm text-ink-soft">
                    <WordText text={m.desc.replace(/^Your goal:\s*/i, '')} />
                  </span>
                </span>
                <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${level.className}`}>{level.label}</span>
                <ChevronRight size={20} className="shrink-0 text-ink-soft" aria-hidden />
              </div>
            </div>
          );
        })}
      </List>
    </Screen>
  );
}
