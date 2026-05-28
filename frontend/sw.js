// ── Cache version — bump this whenever you deploy to force a fresh install ──
const CACHE_VERSION = 'v6';
const CACHE_NAME    = `roadsos-${CACHE_VERSION}`;
const TILE_CACHE    = `roadsos-tiles-${CACHE_VERSION}`;
// NOTE: API responses are NEVER cached — always fetched fresh from the network.

const APP_SHELL = [
  './manifest.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&display=swap',
  // index.html is intentionally NOT in APP_SHELL — it is always fetched from the network.
];

// ── Install — pre-cache static assets only ─────────────────────────────────
self.addEventListener('install', event => {
  console.log(`[SW] Installing cache: ${CACHE_NAME}`);
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())   // activate immediately, don't wait
  );
});

// ── Activate — delete ALL old caches so users always get fresh code ─────────
self.addEventListener('activate', event => {
  console.log(`[SW] Activating, clearing old caches`);
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME && k !== TILE_CACHE)
            .map(k => {
              console.log(`[SW] Deleting stale cache: ${k}`);
              return caches.delete(k);
            })
      ))
      .then(() => self.clients.claim())  // take control of existing pages
  );
});

// ── Fetch — smart routing ───────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. API calls (infrax2026.onrender.com or any /api/ path) — ALWAYS network, never cache
  if (
    url.hostname.includes('onrender.com') ||
    url.hostname.includes('overpass-api.de') ||
    url.hostname.includes('nominatim.openstreetmap.org') ||
    url.pathname.startsWith('/api/')
  ) {
    event.respondWith(
      fetch(req).catch(() => {
        // Network failed — return a graceful JSON error so the frontend can handle it
        return new Response(
          JSON.stringify({ error: 'offline', services: [] }),
          { headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }

  // 2. Map tiles — cache aggressively (tiles don't change)
  if (url.hostname.includes('tile.openstreetmap.org')) {
    event.respondWith(
      caches.open(TILE_CACHE).then(cache =>
        cache.match(req).then(cached => {
          if (cached) return cached;
          return fetch(req).then(response => {
            if (response.ok) cache.put(req, response.clone());
            return response;
          });
        })
      )
    );
    return;
  }

  // 3. index.html — NETWORK FIRST, fall back to cache
  //    This ensures users always get the latest deployed code.
  if (url.pathname === '/' || url.pathname.endsWith('index.html')) {
    event.respondWith(
      fetch(req)
        .then(response => {
          // Update cache with fresh copy
          caches.open(CACHE_NAME).then(c => c.put(req, response.clone()));
          return response;
        })
        .catch(() => caches.match(req))   // offline fallback
    );
    return;
  }

  // 4. Everything else (CSS, JS, fonts) — cache first, network fallback
  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req).then(response => {
        if (response.ok && req.method === 'GET') {
          caches.open(CACHE_NAME).then(c => c.put(req, response.clone()));
        }
        return response;
      }).catch(() => {
        if (req.mode === 'navigate') return caches.match('./index.html');
      });
    })
  );
});
