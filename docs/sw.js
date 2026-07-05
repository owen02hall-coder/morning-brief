// Service worker: cache the app shell (cache-first) but always try the network first for the
// briefing data so the freshest edition shows when online. Bump CACHE on any shell change.
// Briefing data lives in its own UNversioned cache: a shell bump must never delete the
// last-known-good briefing/archives that the offline fallback depends on.
const CACHE = "briefing-shell-v3";   // v3: app.js safe-href/archive-errors/resume-refetch + split data cache
const DATA_CACHE = "briefing-data-v1";
const SHELL = ["./", "./index.html", "./app.js", "./styles.css", "./manifest.json",
               "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE && k !== DATA_CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isData = url.pathname.endsWith("briefing.json") || url.pathname.includes("/archive/");
  if (isData) {
    // network-first for data: freshest when online, last-known when offline. Only cache good
    // responses — a 404/500 body must not overwrite the last-known-good copy the offline
    // fallback serves.
    e.respondWith(
      fetch(e.request).then((r) => {
        if (r.ok) {
          const copy = r.clone();
          caches.open(DATA_CACHE).then((c) => c.put(e.request, copy));
        }
        return r;
      }).catch(() => caches.match(e.request))
    );
  } else {
    // cache-first for the shell
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
