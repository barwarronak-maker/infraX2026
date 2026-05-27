const CACHE = 'roadsos-v1';
const STATIC = [
  '/',
  '/index.html',
  '/manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap'
];

// Map tile domains to cache
const TILE_PATTERN = /^https:\/\/[abc]\.tile\.openstreetmap\.org\//;

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => {
      // Cache static assets, ignore failures for external fonts
      return Promise.allSettled(STATIC.map(url => c.add(url).catch(() => {})));
    }).then(() => self.skipWaiting())
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
  const url = e.request.url;

  // Cache-first for map tiles (offline maps work)
  if (TILE_PATTERN.test(url)) {
    e.respondWith(
      caches.match(e.request).then(cached => {
        if (cached) return cached;
        return fetch(e.request).then(resp => {
          if (resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return resp;
        }).catch(() => cached || new Response('', {status: 503}));
      })
    );
    return;
  }

  // Network-first for API calls (Overpass, Nominatim)
  if (url.includes('overpass-api.de') || url.includes('nominatim.openstreetmap.org')) {
    e.respondWith(
      fetch(e.request).catch(() => new Response(JSON.stringify({elements:[]}), {
        headers: {'Content-Type':'application/json'}
      }))
    );
    return;
  }

  // Cache-first for app shell
  if (url.includes(self.location.origin) || STATIC.includes(url)) {
    e.respondWith(
      caches.match(e.request).then(cached => {
        if (cached) return cached;
        return fetch(e.request).then(resp => {
          if (resp.ok) {
            caches.open(CACHE).then(c => c.put(e.request, resp.clone()));
          }
          return resp;
        }).catch(() => caches.match('/index.html'));
      })
    );
    return;
  }

  // Default: network with fallback
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
