import { describe, expect, test } from 'bun:test';
import {
  controllerChangeIsUpdate,
  getUpdateReady,
  installedIsUpdate,
  isCallHash,
  markUpdateReady,
  shouldShowUpdateBanner,
  startUpdateWatch,
} from './swUpdate';

describe('shouldShowUpdateBanner', () => {
  test('통화 화면(#/call)에서는 업데이트가 준비돼도 숨긴다', () => {
    expect(shouldShowUpdateBanner(true, '#/call')).toBe(false);
    expect(shouldShowUpdateBanner(true, '#/call/')).toBe(false);
  });

  test('통화 화면이 아니면 업데이트가 준비됐을 때 보인다', () => {
    for (const hash of ['', '#/', '#/person/jake', '#/summary', '#/chat/call', '#/calls']) {
      expect(shouldShowUpdateBanner(true, hash)).toBe(true);
    }
  });

  test('업데이트가 준비되지 않았으면 어디서도 숨긴다', () => {
    expect(shouldShowUpdateBanner(false, '#/')).toBe(false);
    expect(shouldShowUpdateBanner(false, '#/call')).toBe(false);
  });

  test('통화를 마치고 나오면(#/call -> #/summary) 그때 보인다', () => {
    expect(shouldShowUpdateBanner(true, '#/call')).toBe(false);
    expect(shouldShowUpdateBanner(true, '#/summary')).toBe(true);
  });
});

describe('isCallHash', () => {
  test('첫 경로 마디가 call일 때만 참이다', () => {
    expect(isCallHash('#/call')).toBe(true);
    expect(isCallHash('#call')).toBe(true);
    expect(isCallHash('#/chat/call')).toBe(false);
    expect(isCallHash('')).toBe(false);
  });
});

describe('업데이트 신호 판별', () => {
  test('처음 설치로 생긴 controllerchange는 업데이트가 아니다', () => {
    expect(controllerChangeIsUpdate(false)).toBe(false);
    expect(controllerChangeIsUpdate(true)).toBe(true);
  });

  test('제어 중인 워커가 있을 때 installed가 된 새 워커만 업데이트다', () => {
    expect(installedIsUpdate('installed', true)).toBe(true);
    expect(installedIsUpdate('installed', false)).toBe(false);
    expect(installedIsUpdate('installing', true)).toBe(false);
  });
});

describe('startUpdateWatch', () => {
  test('다시 보이면 update()를 부르고, 숨겨질 때는 부르지 않는다', () => {
    const handlers: Record<string, () => void> = {};
    const doc = { visibilityState: 'hidden', addEventListener: (t: string, l: () => void) => void (handlers[t] = l) };
    let updates = 0;
    const registration = {
      waiting: null,
      installing: null,
      addEventListener: () => {},
      update: () => (updates++, Promise.resolve()),
    };
    startUpdateWatch({ controller: {}, addEventListener: () => {} }, doc).attach(registration);
    handlers.visibilitychange();
    expect(updates).toBe(0);
    doc.visibilityState = 'visible';
    handlers.visibilitychange();
    expect(updates).toBe(1);
  });

  test('이미 제어 중일 때 controllerchange가 오면 업데이트 준비 상태가 된다', () => {
    let fire = () => {};
    expect(getUpdateReady()).toBe(false);
    startUpdateWatch({ controller: {}, addEventListener: (_t: string, l: () => void) => void (fire = l) }, { visibilityState: 'visible', addEventListener: () => {} });
    fire();
    expect(getUpdateReady()).toBe(true);
    markUpdateReady();
    expect(getUpdateReady()).toBe(true);
  });
});
