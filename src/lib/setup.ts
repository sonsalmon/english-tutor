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

export type CallSetup =
  | { kind: 'mission'; mission: Mission; retry?: Retry | null }
  | { kind: 'freetalk'; topic: string; retry?: Retry | null }
  | { kind: 'smalltalk'; retry?: Retry | null }
  | { kind: 'teachback'; lessonDate: string; dayTitle?: string; sections: LessonSection[]; seniorMode: SeniorMode; retry?: Retry | null };

export type FinishedCall = {
  setup: CallSetup;
  startedAt: number;
  endedAt: number;
  result: MissionResult | null;
  endReason: EndReason | null;
  practiceWords: string[];
};

export function callMode(setup: CallSetup): CallMode {
  return setup.kind;
}

export function callTitle(setup: CallSetup): string {
  if (setup.kind === 'mission') return setup.mission.title;
  if (setup.kind === 'smalltalk') return SMALLTALK_TITLE;
  if (setup.kind === 'teachback') return setup.dayTitle || `Teach-back ${setup.lessonDate}`;
  return setup.topic ? freeTalkTitle(setup.topic) : 'Ms. Park과 자유 대화';
}

export function buildInstruction(setup: CallSetup, brief: string, words: PracticeWord[] = []): string {
  if (setup.kind === 'mission') return missionInstruction(setup.mission, brief, setup.retry, words);
  if (setup.kind === 'smalltalk') return smallTalkInstruction(brief, words);
  if (setup.kind === 'teachback') return teachbackInstruction(setup.sections, setup.seniorMode, setup.retry, brief);
  return freeTalkInstruction(setup.topic, brief, setup.retry, words);
}

// Teach-back은 수업 내용에 집중하도록 readgloss 단어를 넣지 않는다.
export function practiceWordsFor(setup: CallSetup, words: PracticeWord[]): PracticeWord[] {
  return setup.kind === 'teachback' ? [] : words;
}
