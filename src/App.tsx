import { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { DEFAULT_TIME_LIMITS, getLearnerProfile, getTimeLimits, type LearnerProfile, type TimeLimits } from './lib/api';
import { timeLimitFor } from './lib/callTime';
import type { Retry } from './lib/instructions';
import { takePendingLatency } from './lib/latency';
import { PARK_ID } from './lib/partners';
import { go, useRoute, useRouteParam } from './lib/router';
import { friendWordbook } from './lib/shareWordbook';
import { setupPartner, type CallSetup, type FinishedCall } from './lib/setup';
import { Chat } from './screens/Chat';
import { Feed } from './screens/Feed';
import { Home } from './screens/Home';
import { Log } from './screens/Log';
import { Missions } from './screens/Missions';
import { Person } from './screens/Person';
import { Pron } from './screens/Pron';
import { Replay } from './screens/Replay';
import { Settings } from './screens/Settings';
import { Summary } from './screens/Summary';
import { TeachbackPrep } from './screens/TeachbackPrep';
import { Topic } from './screens/Topic';
import { Words } from './screens/Words';

const Call = lazy(() => import('./screens/Call').then((m) => ({ default: m.Call })));

export function App() {
  const route = useRoute();
  const param = useRouteParam();
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [limits, setLimits] = useState<TimeLimits>(DEFAULT_TIME_LIMITS);
  const [setup, setSetup] = useState<CallSetup | null>(null);
  const [callKey, setCallKey] = useState(0);
  const [finished, setFinished] = useState<FinishedCall | null>(null);

  useEffect(() => {
    void getTimeLimits().then(setLimits);
  }, []);

  useEffect(() => {
    // 홈이나 사람 페이지로 돌아올 때마다 통화 뒤 갱신된 학습자 카드를 다시 읽는다.
    if (route === 'home' || route === 'person' || profile === null) void getLearnerProfile().then(setProfile);
  }, [route]);

  useEffect(() => {
    // 옛 주소는 새 주소로 바꿔 치운다(뒤로 가기가 옛 주소로 돌아오지 않게 replace).
    if (route === 'smalltalk') go('home', true);
    else if (route === 'history') go('log', true, param ?? undefined);
    else if (route === 'chat' && !param) go('home', true);
    else if ((route === 'call' && !setup) || (route === 'summary' && !finished)) go('home', true);
  }, [route, param, setup, finished]);

  const retryProfile = useCallback(() => {
    setProfile(null);
    void getLearnerProfile().then(setProfile);
  }, []);

  const startCall = useCallback((next: CallSetup) => {
    setSetup(next);
    setCallKey((k) => k + 1);
    go('call');
  }, []);

  // Ms. Park에게 거는 전화는 자유 대화(공부), 친구에게 거는 전화는 그냥 이야기(smalltalk)다.
  const callPerson = useCallback(
    (partnerId: string) => startCall(partnerId === PARK_ID ? { kind: 'freetalk', topic: '' } : { kind: 'smalltalk', partner: partnerId }),
    [startCall],
  );

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

  const parkHint = profile?.weak_points?.[0]?.pattern;

  const renderScreen = () => {
    switch (route) {
      case 'person':
        return <Person partnerId={param} profile={profile} onCall={callPerson} onRetryProfile={retryProfile} />;
      case 'log':
        return <Log stem={param} parkHint={parkHint} />;
      case 'words':
        return <Words />;
      case 'feed':
        return <Feed />;
      case 'settings':
        return <Settings />;
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
        return param ? (
          <Chat
            partnerId={param}
            brief={profile?.brief ?? ''}
            interests={profile?.interests}
            wordbook={friendWordbook(profile)}
            profileReady={profile !== null}
            onCall={callPerson}
          />
        ) : null;
      case 'call':
        return setup ? (
          <Suspense fallback={null}>
            <Call
              key={callKey}
              setup={setup}
              brief={profile?.brief ?? ''}
              practiceWords={profile?.practice_words ?? []}
              interests={profile?.interests}
              wordbook={friendWordbook(profile)}
              timeLimit={timeLimitFor(setup.kind, limits)}
              onFinished={onFinished}
            />
          </Suspense>
        ) : null;
      case 'summary':
        return finished ? <Summary call={finished} onRetry={retry} onHome={() => go('person', false, setupPartner(finished.setup).id)} /> : null;
      case 'replay':
        return <Replay stem={param} />;
      case 'smalltalk':
      case 'history':
        return null;
      default:
        return <Home profile={profile} onCall={callPerson} onRetryProfile={retryProfile} />;
    }
  };

  return <AppShell route={route}>{renderScreen()}</AppShell>;
}
