// 같은 표현을 말하는 여러 장면(예시 클립)을 차례로 넘길 때의 위치 계산. 끝에서 처음으로 돌아가지 않는다.

// index번째 예시 다음 예시의 위치. 마지막이거나 위치가 범위 밖이면 null.
export function nextExample(index: number, count: number): number | null {
  return index >= 0 && index + 1 < count ? index + 1 : null;
}

// "2/3" 모양의 위치 표시. 예시가 하나뿐이면 빈 글.
export function exampleLabel(index: number, count: number): string {
  return count > 1 && index >= 0 && index < count ? `${index + 1}/${count}` : '';
}
