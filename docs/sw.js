// Service worker: cache the app shell (cache-first) but always try the network first for the
// briefing data so the freshest edition shows when online. Bump CACHE on any shell change.
const CACHE = "briefing-shell-v1";
const SHELL = ["./", "./index.html", "./app.js", "./styles.css", "./manifest.json",
               "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isData = url.pathname.endsWith("briefing.json") || url.pathname.includes("/archive/");
  if (isData) {
    // network-first for data: freshest when online, last-known when offline
    e.respondWith(
      fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      }).catch(() => caches.match(e.request))
    );
  } else {
    // cache-first for the shell
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
