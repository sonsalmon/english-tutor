import { cycleRate, loadPrefs, savePrefs, visibleRates } from '../lib/playerPrefs';

// 요약·피드의 작은 재생기용 속도 칩 하나. 누를 때마다 다음 속도로 돌고, 고른 속도는 공부 화면과 같은 곳에 기억한다.
export function SpeedChip({ rate, rates, disabled, onChange, className }: { rate: number; rates: readonly number[]; disabled: boolean; onChange: (rate: number) => void; className: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={`재생 속도 ${rate}배, 누르면 바뀝니다`}
      onClick={() => {
        const next = cycleRate(visibleRates(rates), rate);
        onChange(next);
        savePrefs({ ...loadPrefs(), rate: next });
      }}
      className={className}
    >
      {rate}x
    </button>
  );
}
