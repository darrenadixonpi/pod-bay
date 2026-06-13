// Pod Bay service worker — app-shell caching for offline/installable PWA.
//
// Caching strategy:
//   Static shell (HTML/CSS/JS/CDN) → pre-cached on install, cache-first
//   API calls (/api/*)             → network-only (always fresh)
//   Diagrams/wiring images         → cache-first, added dynamically on first fetch
//
// Bump CACHE_NAME whenever the shell files change so old caches are evicted.
const CACHE_NAME = 'podbay-v1';

const SHELL = [
  '/',
  '/styles.css',
  '/app.js',
  'https://cdn.jsdelivr.net/npm/marked/marked.min.js',
];

// ── Install: pre-cache the app shell ─────────────────────────────────────────
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then((c) => c.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: evict caches from previous versions ─────────────────────────────
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch: route requests to the right strategy ───────────────────────────────
self.addEventListener('fetch', (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // API: always go to the network — no caching of dynamic data.
  if (url.pathname.startsWith('/api/')) return;

  // Diagrams and wiring images: cache-first + add to cache on first network hit.
  if (url.pathname.startsWith('/diagrams/') || url.pathname.startsWith('/wiring/')) {
    e.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((resp) => {
          if (resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, copy));
          }
          return resp;
        });
      })
    );
    return;
  }

  // Everything else (shell + CDN): cache-first, network fallback.
  e.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((resp) => {
        if (resp.ok && request.method === 'GET') {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((c) => c.put(request, copy));
        }
        return resp;
      });
    })
  );
});

// ── Message: allow the page to trigger skipWaiting for instant updates ────────
self.addEventListener('message', (e) => {
  if (e.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
