import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { getCalls, getLearnerProfile, getTimeLimits, type CallTotals, type LearnerProfile, type TimeLimits } from './lib/api';
import type { Retry } from './lib/instructions';
import { takePendingLatency } from './lib/latency';
import { go, useRoute, useRouteParam } from './lib/router';
import type { CallSetup, FinishedCall } from './lib/setup';
import { Chat } from './screens/Chat';
import { CallHistory } from './screens/History';
import { Home } from './screens/Home';
import { Missions } from './screens/Missions';
import { Pron } from './screens/Pron';
import { Replay } from './screens/Replay';
import { Summary } from './screens/Summary';
import { TeachbackPrep } from './screens/TeachbackPrep';
import { Topic } from './screens/Topic';

const Call = lazy(() => import('./screens/Call').then((m) => ({ default: m.Call })));

export function App() {
  const route = useRoute();
  const param = useRouteParam();
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [totals, setTotals] = useState<CallTotals | null>(null);
  const [limits, setLimits] = useState<TimeLimits>({ call: 600, teachback: 900, smalltalk: 300 });
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
    // 사이드바의 스몰토크는 화면 없이 바로 통화를 시작한다. 뒤로 가기가 다시 시작하지 않도록 이 주소는 바꿔 치운다.
    if (route === 'smalltalk') {
      setSetup({ kind: 'smalltalk' });
      setCallKey((k) => k + 1);
      go('call', true);
    }
  }, [route]);

  useEffect(() => {
    if ((route === 'call' && !setup) || (route === 'summary' && !finished)) go('home', true);
  }, [route, setup, finished]);

  const startSmallTalk = useCallback(() => {
    setSetup({ kind: 'smalltalk' });
    setCallKey((k) => k + 1);
    go('call');
  }, []);

  const retryProfile = useCallback(() => {
    setProfile(null);
    void getLearnerProfile().then(setProfile);
  }, []);

  const startCall = useCallback((next: CallSetup) => {
    setSetup(next);
    setCallKey((k) => k + 1);
    go('call');
  }, []);

  const onFinished = useCallback((call: FinishedCall) => {
    setFinished({ ...call, latency: takePendingLatency() });
    go('summary', true);
  }, []);

  const retry = useCallback(
    (notes: Retry) => {
      if (finished) startCall({ ...finished.setup, retry: notes });
    },
    [finished, startCall],
  );

  const renderScreen = () => {
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
      case 'pron':
        return <Pron />;
      case 'chat':
        return (
          <Chat
            partnerId={param}
            brief={profile?.brief ?? ''}
            interests={profile?.interests}
            profileReady={profile !== null}
            onCall={(partner) => startCall({ kind: 'smalltalk', partner })}
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
              interests={profile?.interests}
              timeLimit={setup.kind === 'teachback' ? limits.teachback : setup.kind === 'smalltalk' ? limits.smalltalk : limits.call}
              onFinished={onFinished}
            />
          </Suspense>
        ) : null;
      case 'summary':
        return finished ? <Summary call={finished} onRetry={retry} /> : null;
      case 'history':
        return <CallHistory stem={param} />;
      case 'replay':
        return <Replay stem={param} />;
      default:
        return <Home profile={profile} totals={totals} onQuickCall={() => startCall({ kind: 'freetalk', topic: '' })} onSmallTalk={startSmallTalk} onRetryProfile={retryProfile} />;
    }
  };

  return <AppShell route={route}>{renderScreen()}</AppShell>;
}
