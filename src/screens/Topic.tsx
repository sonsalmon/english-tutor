import { Phone } from 'lucide-react';
import { useState } from 'react';
import { CallButton, Screen, TopBar } from '../components/ui';
import { TOPIC_MAX, sanitizeTopic } from '../lib/instructions';
import { PARK_ID } from '../lib/partners';
import { go } from '../lib/router';

export function Topic({ onStart }: { onStart: (topic: string) => void }) {
  const [topic, setTopic] = useState('');
  const atLimit = topic.length >= TOPIC_MAX;
  return (
    <Screen>
      <TopBar title="주제 정해서 대화" onBack={() => go('person', false, PARK_ID)} />
      <label htmlFor="topic" className="font-semibold">
        오늘 이야기할 주제나 글
      </label>
      <p className="mt-1 text-sm leading-relaxed text-ink-soft">
        한 줄 주제도 좋고, 기사나 메모를 통째로 붙여 넣어도 돼요. Ms. Park은 역할극 없이 그 내용으로 대화해요.
      </p>
      <textarea
        id="topic"
        value={topic}
        maxLength={TOPIC_MAX}
        onChange={(e) => setTopic(e.target.value)}
        rows={8}
        placeholder="예: How to explain least privilege to a new teammate"
        className="mt-3 w-full resize-y rounded-2xl border border-line bg-surface p-4 text-base leading-relaxed placeholder:text-ink-soft/70"
      />
      <p className={`mt-2 text-right text-sm tabular-nums ${atLimit ? 'text-end-press' : 'text-ink-soft'}`} aria-live="polite">
        {topic.length.toLocaleString('ko-KR')} / {TOPIC_MAX.toLocaleString('ko-KR')}
        {atLimit && ' · 넘는 글은 잘려요'}
      </p>
      <div className="mt-auto pt-8">
        <CallButton onClick={() => onStart(sanitizeTopic(topic))}>
          <Phone size={22} aria-hidden />
          {topic.trim() ? '이 주제로 전화하기' : '주제 없이 전화하기'}
        </CallButton>
      </div>
    </Screen>
  );
}
