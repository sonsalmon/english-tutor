// 배포 뒤에도 켜 둔 홈 화면 앱이 옛 JS를 쓰는 문제를 막는다. 새 서비스 워커가 준비되면 배너를 띄운다.
// 판단은 순수 함수로 두고, 브라우저 이벤트 연결(startUpdateWatch)은 얇게 유지한다.

// 해시 경로의 첫 마디가 call이면 통화 화면이다(#/call, #/call/...).
export function isCallHash(hash: string): boolean {
  return hash.replace(/^#\/?/, '').split('/')[0] === 'call';
}

// 통화 중에는 배너도 새로고침도 없다. 통화 화면을 벗어나면 그때 보인다.
export function shouldShowUpdateBanner(updateReady: boolean, hash: string): boolean {
  return updateReady && !isCallHash(hash);
}

// 처음 설치(이전에 제어하던 워커가 없음)에서도 controllerchange가 오지만, 그건 업데이트가 아니다.
export function controllerChangeIsUpdate(hadControllerAtStart: boolean): boolean {
  return hadControllerAtStart;
}

// 이미 페이지를 제어하는 워커가 있는 상태에서 새 워커가 설치를 마치면 업데이트다.
export function installedIsUpdate(workerState: string, hasController: boolean): boolean {
  return workerState === 'installed' && hasController;
}

let updateReady = false;
const listeners = new Set<() => void>();

export function getUpdateReady(): boolean {
  return updateReady;
}

export function subscribeUpdateReady(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function markUpdateReady(): void {
  if (updateReady) return;
  updateReady = true;
  listeners.forEach((listener) => listener());
}

type WorkerLike = { state: string; addEventListener(type: 'statechange', listener: () => void): void };
type RegistrationLike = {
  waiting: unknown;
  installing: WorkerLike | null;
  addEventListener(type: 'updatefound', listener: () => void): void;
  update(): Promise<unknown>;
};
type ContainerLike = { controller: unknown; addEventListener(type: 'controllerchange', listener: () => void): void };
type DocumentLike = { visibilityState: string; addEventListener(type: 'visibilitychange', listener: () => void): void };

// 페이지가 열릴 때의 제어 여부를 바로 기록하고 controllerchange를 구독한다. 등록이 끝나면 attach로 나머지를 잇는다.
export function startUpdateWatch(container: ContainerLike, doc: DocumentLike) {
  const hadControllerAtStart = Boolean(container.controller);
  container.addEventListener('controllerchange', () => {
    if (controllerChangeIsUpdate(hadControllerAtStart)) markUpdateReady();
  });

  return {
    attach(registration: RegistrationLike) {
      if (registration.waiting && container.controller) markUpdateReady();
      registration.addEventListener('updatefound', () => {
        const worker = registration.installing;
        worker?.addEventListener('statechange', () => {
          if (installedIsUpdate(worker.state, Boolean(container.controller))) markUpdateReady();
        });
      });
      // 홈 화면 앱은 백그라운드에서 되살아날 뿐 다시 로드되지 않으므로, 다시 보일 때마다 새 버전을 확인한다.
      doc.addEventListener('visibilitychange', () => {
        if (doc.visibilityState === 'visible') void registration.update().catch(() => {});
      });
    },
  };
}
