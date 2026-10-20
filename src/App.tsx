import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { getCalls, getLearnerProfile, getTimeLimits, type CallTotals, type LearnerProfile, type TimeLimits } from './lib/api';
import type { Retry } from './lib/instructions';
import { go, useRoute, useRouteParam } from './lib/router';
import type { CallSetup, FinishedCall } from './lib/setup';
import { CallHistory } from './screens/History';
import { Home } from './screens/Home';
import { Missions } from './screens/Missions';
import { Summary } from './screens/Summary';
import { TeachbackPrep } from './screens/TeachbackPrep';
import { Topic } from './screens/Topic';

const Call = lazy(() => import('./screens/Call').then((m) => ({ default: m.Call })));

export function App() {
  const route = useRoute();
  const param = useRouteParam();
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [totals, setTotals] = useState<CallTotals | null>(null);
  const [limits, setLimits] = useState<TimeLimits>({ call: 600, teachback: 900 });
  const [setup, setSetup] = useState<CallSetup | null>(null);
  const [callKey, setCallKey] = useState(0);
  const [finished, setFinished] = useState<FinishedCall | null>(null);

  useEffect(() => {
    void getTimeLimits().then(setLimits);
  }, []);

  useEffect(() => {
    if (route === 'home' || profile === null) void getLearnerProfile().then(setProfile);
    // 홈으로 돌아올 때마다 통화 뒤 갱신된 학습자 카드를 다시 읽는다.
  }, [route]);

  useEffect(() => {
    if (route !== 'home') return;
    const controller = new AbortController();
    getCalls(1, controller.signal).then(
      (data) => setTotals(data.totals),
      () => {},
    );
    return () => controller.abort();
  }, [route]);

  useEffect(() => {
    if ((route === 'call' && !setup) || (route === 'summary' && !finished)) go('home', true);
  }, [route, setup, finished]);

  const startCall = useCallback((next: CallSetup) => {
    setSetup(next);
    setCallKey((k) => k + 1);
    go('call');
  }, []);

  const onFinished = useCallback((call: FinishedCall) => {
    setFinished(call);
    go('summary', true);
  }, []);

  const retry = useCallback(
    (notes: Retry) => {
      if (finished) startCall({ ...finished.setup, retry: notes });
    },
    [finished, startCall],
  );

  switch (route) {
    case 'missions':
      return <Missions onPick={(mission) => startCall({ kind: 'mission', mission })} />;
    case 'topic':
      return <Topic onStart={(topic) => startCall({ kind: 'freetalk', topic })} />;
    case 'teachback':
      return (
        <TeachbackPrep
          onStart={(lesson, seniorMode) =>
            startCall({ kind: 'teachback', lessonDate: lesson.date, dayTitle: lesson.day_title, sections: lesson.sections, seniorMode })
          }
        />
      );
    case 'call':
      return setup ? (
        <Suspense fallback={null}>
          <Call
            key={callKey}
            setup={setup}
            brief={profile?.brief ?? ''}
            practiceWords={profile?.practice_words ?? []}
            timeLimit={setup.kind === 'teachback' ? limits.teachback : limits.call}
            onFinished={onFinished}
          />
        </Suspense>
      ) : null;
    case 'summary':
      return finished ? <Summary call={finished} onRetry={retry} /> : null;
    case 'history':
      return <CallHistory stem={param} />;
    default:
      return <Home profile={profile} totals={totals} onQuickCall={() => startCall({ kind: 'freetalk', topic: '' })} />;
  }
}
