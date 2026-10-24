import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { startUpdateWatch } from './lib/swUpdate';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// 서비스 워커는 빌드한 앱에서만 켠다. 개발 서버(vite)에서는 캐시가 코드 수정을 가리기 때문이다.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  // 열릴 때 이미 서비스 워커가 제어 중이었는지 바로 기록해, 처음 설치와 업데이트를 구분한다.
  const updates = startUpdateWatch(navigator.serviceWorker, document);
  window.addEventListener('load', () => {
    void navigator.serviceWorker
      .register('/sw.js')
      .then(updates.attach)
      .catch(() => {});
  });
}
