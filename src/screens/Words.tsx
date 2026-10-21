import { Screen } from '../components/ui';

// 자리표시 화면. 단어와 문장 목록은 다음 티켓(T5)이 이 파일을 교체한다.
export function Words() {
  return (
    <Screen>
      <header className="flex h-11 items-center lg:mb-4 lg:h-auto">
        <h1 className="text-[28px] font-bold">단어장</h1>
      </header>
      <p className="mt-4 leading-relaxed text-ink-soft">읽다가 찾아본 단어와 저장한 문장이 여기에 모일 거예요. 아직 준비 중이에요.</p>
    </Screen>
  );
}
