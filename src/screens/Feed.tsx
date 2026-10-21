import { Screen } from '../components/ui';

// 자리표시 화면. 영어 표현 클립 피드는 다음 티켓(T5)이 이 파일을 교체한다.
export function Feed() {
  return (
    <Screen>
      <header className="flex h-11 items-center lg:mb-4 lg:h-auto">
        <h1 className="text-[28px] font-bold">클립</h1>
      </header>
      <p className="mt-4 leading-relaxed text-ink-soft">영어 표현 클립을 위아래로 넘겨 볼 수 있게 될 거예요. 아직 준비 중이에요.</p>
    </Screen>
  );
}
