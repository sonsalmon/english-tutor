import { useState } from 'react';
import { loadScreenMode, saveScreenMode, type ScreenMode } from '../lib/screenLock';

const OPTIONS: { value: ScreenMode; label: string; desc: string }[] = [
  { value: 'system', label: '자동으로 꺼짐 허용', desc: '휴대폰 설정대로 화면이 꺼져요. 꺼지면 마이크가 멈출 수 있어요.' },
  { value: 'keep', label: '켜 두기', desc: '통화 중에는 화면이 꺼지지 않아요.' },
  { value: 'black', label: '검은 화면', desc: '켜 두기에 더해 연결 5초 뒤 화면을 까맣게 덮어요. 귀에 대도 끊기지 않고, 손잡이를 오른쪽으로 밀면 풀려요.' },
];

// 통화 중 화면 설정. 네이티브 라디오라 방향키와 스크린 리더가 그대로 동작한다.
export function ScreenSettings() {
  const [mode, setMode] = useState<ScreenMode>(() => loadScreenMode());
  const choose = (value: ScreenMode) => {
    setMode(value);
    saveScreenMode(value);
  };
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 font-bold">통화 중 화면</legend>
      <div className="space-y-2">
        {OPTIONS.map((o) => (
          <label key={o.value} className="relative block">
            <input type="radio" name="screen-mode" value={o.value} checked={mode === o.value} onChange={() => choose(o.value)} className="peer sr-only" />
            <span className="block min-h-14 cursor-pointer rounded-2xl border border-line bg-surface px-4 py-3 peer-checked:border-ink peer-checked:ring-1 peer-checked:ring-ink peer-focus-visible:outline-3 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink/45">
              <span className="block font-semibold">{o.label}</span>
              <span className="mt-0.5 block text-sm text-ink-soft">{o.desc}</span>
            </span>
          </label>
        ))}
      </div>
      <p className="mt-3 text-sm text-ink-soft">
        웹에서는 화면 전원을 진짜로 끌 수 없어요. 아이폰 웹 앱에서는 귀에 대면 꺼지는 근접 센서도 쓸 수 없어서, 검은 화면 모드가 그 역할을 대신해요.
      </p>
    </fieldset>
  );
}
