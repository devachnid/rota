// The service worker. Its job is narrow and worth stating, because a worker
// in an authenticated app is where a stale schedule or a logged-out user's
// page would come from if it were allowed to cache freely:
//
//   - It stores exactly one thing, the offline page, at install.
//   - It touches only navigations (a tap on a link, a start from the home
//     screen). Every htmx partial, form post and script goes to the network
//     untouched, because the handler never calls respondWith for them.
//   - A navigation that fails gets the offline page. One that succeeds is
//     never stored.
//
// Chrome on Android offers "Install app" (a real standalone window) only to a
// site with a worker that handles fetch; without one it offers a shortcut.
// That is why this file exists. It is served at /sw.js by config.views so its
// scope can be the whole site — a worker cannot control paths above its own.

const CACHE = 'rota-offline-v1';
const PRECACHE = ['/offline/'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  // A new worker drops the caches of the old one, so a redesigned offline
  // page is not shadowed by the previous version's copy.
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(PRECACHE[0]))
  );
});
