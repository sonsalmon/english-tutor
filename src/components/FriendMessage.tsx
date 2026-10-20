import type { FriendMessage as FriendMessageData } from '../lib/api';
import { isPark, partnerById } from '../lib/partners';
import { WordText } from './WordText';

// 통화가 끝난 뒤 대화 상대가 보내는 짧은 메시지. 이번 통화에서 나온 표현만 담겨 있다.
// 없으면(옛 기록, teach-back) 아무것도 그리지 않는다.
export function FriendMessage({ message, partnerId }: { message?: FriendMessageData | null; partnerId?: string | null }) {
  if (!message || !message.phrases.length) return null;
  const partner = partnerById(partnerId);
  return (
    <section className="mt-6" aria-labelledby="friend-message-title">
      <div className="flex items-center gap-3">
        <span className="size-10 shrink-0 overflow-hidden rounded-full bg-line">
          <img src={partner.portrait} alt="" width={40} height={40} className={`size-full object-cover ${isPark(partner) ? '' : 'scale-[1.15]'}`} />
        </span>
        <h2 id="friend-message-title" className="text-lg font-bold">
          {partner.name}의 메시지
        </h2>
      </div>
      <div lang="en" className="mt-3 rounded-2xl rounded-tl-md border border-line bg-surface p-5 leading-relaxed">
        {message.opening && <p className="text-[17px] font-semibold">{message.opening}</p>}
        <ul className={`space-y-3 ${message.opening ? 'mt-4' : ''}`}>
          {message.phrases.map((p, i) => (
            <li key={i}>
              <span className="block font-semibold break-words">
                <WordText text={p.phrase} />
              </span>
              {p.note && (
                <span className="mt-0.5 block text-sm text-ink-soft">
                  <WordText text={p.note} />
                </span>
              )}
            </li>
          ))}
        </ul>
        {message.next_time && (
          <p className="mt-4 border-t border-line pt-4">
            <WordText text={message.next_time} />
          </p>
        )}
      </div>
    </section>
  );
}
