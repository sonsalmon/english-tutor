// 앱 껍데기만 캐시한다. /api/* 는 절대 캐시하지 않는다(통화·채팅·기록은 항상 서버 최신값).
// 배포로 캐시 구조가 바뀌면 CACHE 이름만 올린다. 활성화될 때 다른 이름의 캐시는 모두 지운다.
const CACHE = 'english-friends-v1';

const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
  '/ms-park.webp',
  '/partners/carmen.webp',
  '/partners/chloe.webp',
  '/partners/jake.webp',
  '/partners/lukas.webp',
  '/partners/omar.webp',
  '/partners/priya.webp',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

// 빌드 산출물(/assets/*)은 파일 이름에 해시가 붙어 내용이 바뀌면 이름도 바뀐다. 한 번 받으면 캐시를 먼저 쓴다.
const isStaticAsset = (url) =>
  url.pathname.startsWith('/assets/') ||
  url.pathname.startsWith('/icons/') ||
  url.pathname.startsWith('/partners/') ||
  url.pathname === '/ms-park.webp' ||
  url.pathname === '/manifest.webmanifest';

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || request.headers.has('range')) return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    // 네트워크 우선: 새 빌드를 바로 받고, 오프라인이면 마지막으로 받은 index.html로 연다.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(CACHE).then((cache) => cache.put('/index.html', copy));
          }
          return response;
        })
        .catch(() => caches.match('/index.html').then((cached) => cached || Response.error())),
    );
    return;
  }

  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
  }
});
