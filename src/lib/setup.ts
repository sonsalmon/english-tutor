import type { PartnerMemory, Wordbook } from './api';
import type { CallMode, EndReason, MissionResult } from './useCall';
import {
  freeTalkInstruction,
  freeTalkTitle,
  missionInstruction,
  smallTalkInstruction,
  SMALLTALK_TITLE,
  teachbackInstruction,
  type LessonSection,
  type Mission,
  type PracticeWord,
  type Retry,
  type SeniorMode,
} from './instructions';
import type { LatencyResult } from './latency';
import type { SharedClip } from './share';
import { isPark, partnerById } from './partners';

// partner는 대화 상대 id다. 없으면 Ms. Park. Teach-back은 언제나 Ms. Park이다.
export type CallSetup =
  | { kind: 'mission'; mission: Mission; retry?: Retry | null; partner?: string }
  | { kind: 'freetalk'; topic: string; retry?: Retry | null; partner?: string; chip?: string }
  | { kind: 'smalltalk'; retry?: Retry | null; partner?: string; chip?: string }
  | { kind: 'teachback'; lessonDate: string; dayTitle?: string; sections: LessonSection[]; seniorMode: SeniorMode; retry?: Retry | null };

export type FinishedCall = {
  setup: CallSetup;
  startedAt: number;
  endedAt: number;
  /** 일시정지로 멈춰 있던 시간(ms). 통화 시간에서 뺀다. */
  pausedMs: number;
  result: MissionResult | null;
  endReason: EndReason | null;
  practiceWords: string[];
  /** 통화 중 파트너가 보낸 영상 장면. 요약 화면에 목록으로 보인다. */
  sharedClips?: SharedClip[];
  /** 이 통화의 응답 속도 측정값. Summary가 튜터링 요청에 실어 서버로 보낸다. */
  latency?: LatencyResult | null;
};

export function callMode(setup: CallSetup): CallMode {
  return setup.kind;
}

export function setupPartner(setup: CallSetup) {
  return setup.kind === 'teachback' ? partnerById(undefined) : partnerById(setup.partner);
}

export function callTitle(setup: CallSetup): string {
  const partner = setupPartner(setup);
  const withPartner = isPark(partner) ? '' : ` with ${partner.name}`;
  if (setup.kind === 'mission') return `${setup.mission.title}${withPartner}`;
  if (setup.kind === 'smalltalk') return `${SMALLTALK_TITLE}${withPartner}`;
  if (setup.kind === 'teachback') return setup.dayTitle || `Teach-back ${setup.lessonDate}`;
  if (!isPark(partner)) return `${setup.topic ? freeTalkTitle(setup.topic) : '자유 대화'}${withPartner}`;
  return setup.topic ? freeTalkTitle(setup.topic) : 'Ms. Park과 자유 대화';
}

export function buildInstruction(setup: CallSetup, brief: string, words: PracticeWord[] = [], interests: string[] = [], memory: PartnerMemory | null = null, wordbook: Wordbook | null = null): string {
  const partner = setupPartner(setup);
  if (setup.kind === 'mission') return missionInstruction(setup.mission, brief, setup.retry, words, partner, interests);
  if (setup.kind === 'smalltalk') return smallTalkInstruction(brief, words, partner, interests, memory, setup.chip, wordbook);
  if (setup.kind === 'teachback') return teachbackInstruction(setup.sections, setup.seniorMode, setup.retry, brief);
  return freeTalkInstruction(setup.topic, brief, setup.retry, words, partner, interests, memory, setup.chip, wordbook);
}

// Teach-back은 수업 내용에 집중하도록 readgloss 단어를 넣지 않는다.
// 친구 통화는 내 단어장의 단어(최대 8개)를 써 볼 단어로 삼는다. 단어장이 비었거나 공유를 껐으면 찾아본 단어를 쓴다.
export function practiceWordsFor(setup: CallSetup, words: PracticeWord[], wordbook: Wordbook | null = null): PracticeWord[] {
  if (setup.kind === 'teachback') return [];
  if (!isPark(setupPartner(setup)) && wordbook?.words?.length) {
    return wordbook.words.slice(0, 8).map((w) => ({ lemma: w.lemma, gloss: w.gloss, source: 'wordbook' }));
  }
  return words;
}
