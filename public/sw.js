// 앱 껍데기만 캐시한다. /api/* 는 절대 캐시하지 않는다(통화·채팅·기록은 항상 서버 최신값).
// 배포로 캐시 구조가 바뀌면 CACHE 이름만 올린다. 활성화될 때 다른 이름의 캐시는 모두 지운다.
const CACHE = 'english-friends-v3';

const PRECACHE = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
  '/ms-park.webp',
  '/partners/brian.webp',
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
      .then(pruneAssets)
      .then(() => self.clients.claim()),
  );
});

// 현재 index.html이 가리키지 않는 옛 /assets/* 항목을 지운다. 실패하면(오프라인 등) 아무것도 지우지 않는다.
// 지연 로딩 조각은 index.html에 없어 지워질 수 있지만, cache-first가 필요할 때 네트워크에서 다시 받는다.
function pruneAssets() {
  return fetch('/index.html', { cache: 'no-store' })
    .then((response) => (response.ok ? response.text() : Promise.reject(new Error('index.html'))))
    .then((html) => {
      const live = new Set(html.match(/\/assets\/[^"'\s)<>]+/g) || []);
      if (!live.size) return undefined;
      return caches.open(CACHE).then((cache) =>
        cache.keys().then((requests) =>
          Promise.all(
            requests
              .filter((request) => {
                const { pathname } = new URL(request.url);
                return pathname.startsWith('/assets/') && !live.has(pathname);
              })
              .map((request) => cache.delete(request)),
          ),
        ),
      );
    })
    .catch(() => undefined);
}

// 빌드 산출물(/assets/*)은 파일 이름에 해시가 붙어 내용이 바뀌면 이름도 바뀐다. 한 번 받으면 캐시를 먼저 쓴다(cache-first).
const isHashedAsset = (url) => url.pathname.startsWith('/assets/');
// 이름에 해시가 없는 정적 파일은 캐시를 먼저 주되 뒤에서 새로 받아 덮어쓴다(stale-while-revalidate).
const isUnhashedStatic = (url) =>
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

  if (isHashedAsset(url)) {
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
    return;
  }

  if (isUnhashedStatic(url)) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const refresh = fetch(request)
            .then((response) => {
              if (response.ok) void cache.put(request, response.clone());
              return response;
            })
            .catch(() => cached || Response.error());
          if (cached) {
            event.waitUntil(refresh);
            return cached;
          }
          return refresh;
        }),
      ),
    );
  }
});
