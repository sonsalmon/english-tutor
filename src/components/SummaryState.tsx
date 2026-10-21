import { LoaderCircle } from 'lucide-react';
import type { SummaryStatus } from '../lib/summaryStatus';
import { QuietButton } from './ui';

// 통화 목록의 한 줄에 붙는 작은 표시. 요약이 있거나(done) 아직 시작 전(pending)이면 아무것도 없다.
export function SummaryBadge({ status }: { status: SummaryStatus | undefined }) {
  if (status === 'running') {
    return (
      <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold" role="status">
        <LoaderCircle size={12} className="animate-spin" aria-hidden />
        정리하는 중
      </span>
    );
  }
  if (status === 'failed') return <span className="shrink-0 rounded-full bg-paper px-2.5 py-1 text-xs font-semibold text-end-press">정리 실패</span>;
  return null;
}

// 통화 상세의 요약 자리: 요약이 아직 없을 때 상태를 알려 주고, 시작 전이거나 실패했으면 정리를 시작하는 버튼을 준다.
export function SummaryPlaceholder({
  status,
  onStart,
  starting,
  startFailed,
}: {
  status: SummaryStatus;
  onStart: () => void;
  starting: boolean;
  startFailed: boolean;
}) {
  if (status === 'running') {
    return (
      <div className="mt-8 flex flex-col items-center gap-3 text-center text-ink-soft" role="status">
        <LoaderCircle size={28} className="animate-spin" aria-hidden />
        <p>정리하는 중이에요. 끝나면 이 자리에 요약이 나타나요.</p>
      </div>
    );
  }
  if (status === 'done') return <p className="mt-8 leading-relaxed text-ink-soft">이 통화는 저장된 요약이 없어요.</p>;
  return (
    <div className="mt-8">
      <p className="leading-relaxed text-ink-soft">{status === 'failed' ? '요약을 만들지 못했어요.' : '이 통화는 아직 요약이 없어요.'}</p>
      {startFailed && (
        <p className="mt-2 text-end-press" role="alert">
          정리를 시작하지 못했어요. 잠시 뒤에 다시 눌러 주세요.
        </p>
      )}
      <div className="mt-3">
        {starting ? <p className="text-ink-soft">시작하는 중이에요.</p> : <QuietButton onClick={onStart}>{status === 'failed' ? '다시 정리하기' : '정리하기'}</QuietButton>}
      </div>
    </div>
  );
}
