const CACHE = 'bonsai-focus-v1';
const ASSETS = [
  '/focus/',
  '/focus/index.html',
  '/focus/app.js',
  '/focus/tree.js',
  '/focus/audio.js',
  '/focus/storage.js',
  '/focus/manifest.json',
  '/focus/icon-192.svg',
  '/focus/icon-512.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (!e.request.url.includes('/focus')) return;
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request).then(resp => {
      const clone = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, clone));
      return resp;
    }))
  );
});
