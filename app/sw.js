// Service worker: makes the whole app, including the dictionary database,
// available offline. scripts/build-app.mjs fills in the placeholders.
//
// Two caches: the app shell (versioned by a hash of all app files) and the
// data (versioned by the database's own hash), so an app-only update does
// not re-download the 12 MB dictionary.

const SHELL_CACHE = 'apte-shell-__APP_VERSION__';
const DATA_CACHE = 'apte-data-__DATA_VERSION__';
const SHELL_FILES = __SHELL_FILES__;
const DATA_FILES = __DATA_FILES__;

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    await (await caches.open(SHELL_CACHE)).addAll(SHELL_FILES);
    const data = await caches.open(DATA_CACHE);
    for (const f of DATA_FILES) {
      if (!(await data.match(f))) await data.add(f);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, DATA_CACHE]);
    for (const name of await caches.keys()) {
      if (name.startsWith('apte-') && !keep.has(name)) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

// Cache first; the network is only a fallback for anything not precached.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const hit = await caches.match(req, { ignoreSearch: true });
    if (hit) return hit;
    if (req.mode === 'navigate') {
      const shell = await caches.match('./index.html');
      if (shell) return shell;
    }
    return fetch(req);
  })());
});
