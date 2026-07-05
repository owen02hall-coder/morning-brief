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
  e.waitUntil((async () => {
    // Migrate briefing data out of outgoing caches BEFORE deleting them: pre-v3 workers stored
    // briefing.json/archives inside the versioned shell cache, so deleting without copying would
    // wipe every existing user's offline fallback exactly once, on upgrade.
    const keys = await caches.keys();
    const data = await caches.open(DATA_CACHE);
    for (const k of keys) {
      if (k === CACHE || k === DATA_CACHE) continue;
      const old = await caches.open(k);
      for (const req of await old.keys()) {
        const url = new URL(req.url);
        if (url.pathname.endsWith("briefing.json") || url.pathname.includes("/archive/")) {
          const hit = await data.match(req);
          if (!hit) {
            const res = await old.match(req);
            if (res) await data.put(req, res);
          }
        }
      }
      await caches.delete(k);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isData = url.pathname.endsWith("briefing.json") || url.pathname.includes("/archive/");
  if (isData) {
    // network-first for data: freshest when online, last-known when offline OR when the server
    // answers with an error (e.g. Pages mid-deploy 404) — an error body must neither overwrite
    // nor mask the last-known-good copy.
    e.respondWith(
      fetch(e.request).then((r) => {
        if (r.ok) {
          const copy = r.clone();
          caches.open(DATA_CACHE).then((c) => c.put(e.request, copy));
          return r;
        }
        return caches.match(e.request).then((m) => m || r);
      }).catch(() => caches.match(e.request))
    );
  } else {
    // cache-first for the shell
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
