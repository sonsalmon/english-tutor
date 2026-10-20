import type { CallMode, EndReason, MissionResult } from './useCall';
import {
  freeTalkInstruction,
  freeTalkTitle,
  missionInstruction,
  teachbackInstruction,
  type LessonSection,
  type Mission,
  type Retry,
  type SeniorMode,
} from './instructions';

export type CallSetup =
  | { kind: 'mission'; mission: Mission; retry?: Retry | null }
  | { kind: 'freetalk'; topic: string; retry?: Retry | null }
  | { kind: 'teachback'; lessonDate: string; dayTitle?: string; sections: LessonSection[]; seniorMode: SeniorMode; retry?: Retry | null };

export type FinishedCall = {
  setup: CallSetup;
  startedAt: number;
  endedAt: number;
  result: MissionResult | null;
  endReason: EndReason | null;
};

export function callMode(setup: CallSetup): CallMode {
  return setup.kind;
}

export function callTitle(setup: CallSetup): string {
  if (setup.kind === 'mission') return setup.mission.title;
  if (setup.kind === 'teachback') return setup.dayTitle || `Teach-back ${setup.lessonDate}`;
  return setup.topic ? freeTalkTitle(setup.topic) : 'Ms. Park과 자유 대화';
}

export function buildInstruction(setup: CallSetup, brief: string): string {
  if (setup.kind === 'mission') return missionInstruction(setup.mission, brief, setup.retry);
  if (setup.kind === 'teachback') return teachbackInstruction(setup.sections, setup.seniorMode, setup.retry);
  return freeTalkInstruction(setup.topic, brief, setup.retry);
}
