// Service worker: cache the app shell (cache-first) but always try the network first for the
// briefing data so the freshest edition shows when online. Bump CACHE on any shell change.
// Briefing data lives in its own UNversioned cache: a shell bump must never delete the
// last-known-good briefing/archives that the offline fallback depends on.
const CACHE = "briefing-shell-v16";  // v16: the audio no longer re-reads a story the must-knows already told; v15: "Across the country" US national news section; v14: audio reads the 10-year, the 30-year mortgage and the VIX with the reason for each, adds the Monday policy digest, and reads a story filed in both tech and world only once; v13: Owen's Alphabet Soup (lesson deck + chained audio queue); v12: mortgage tile shows a week-over-week delta in bps; v11: static policy calendar in "What's coming"; v10: policy section + mortgage tile; v9: two-index breadth cards; v8: leaner narration; v7: breadth number
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
    // Scoped to THIS app's caches and paths: caches.keys() is origin-wide, and github.io project
    // sites share one origin — never touch a sibling app's caches or ingest its files.
    const scopePath = new URL(self.registration.scope).pathname;
    const keys = await caches.keys();
    const data = await caches.open(DATA_CACHE);
    for (const k of keys) {
      if (k === CACHE || k === DATA_CACHE || !k.startsWith("briefing-")) continue;
      try { // one broken cache must not abort migration/cleanup of the rest (or clients.claim)
        const old = await caches.open(k);
        for (const req of await old.keys()) {
          const url = new URL(req.url);
          if (url.pathname.startsWith(scopePath) &&
              (url.pathname.endsWith("briefing.json") || url.pathname.includes("/archive/"))) {
            const hit = await data.match(req);
            if (!hit) {
              const res = await old.match(req);
              // pre-v3 workers cached responses with NO ok-gate: only promote GOOD bodies, or the
              // migration would enshrine a stale 404/500 as the "last-known-good" offline copy
              if (res && res.ok) await data.put(req, res);
            }
          }
        }
        await caches.delete(k);
      } catch (err) { /* leftover cache is storage bloat, not data loss — next bump retries */ }
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Audio edition: never intercept. Media playback needs native Range-request handling (SW
  // cache.match breaks seeking in Safari), and the manifest must always be network-fresh — a
  // cached manifest could bind yesterday's mp3 to today's page.
  // Lesson clips are media too, and for the same reason: Range requests and seeking must reach the
  // network untouched. They are also short-lived on the server (pruned to a rolling window), so a
  // cached copy would outlive the deck entry that points at it.
  if (url.pathname.endsWith("briefing-audio.mp3") || url.pathname.endsWith("briefing-audio.json") ||
      (url.pathname.includes("/lessons/") && url.pathname.endsWith(".mp3"))) {
    return;
  }
  // lessons.json is DATA, not shell: network-first so a new lesson appears the morning it lands,
  // last-known-good when offline. Cached in DATA_CACHE, which shell bumps never clear — the deck
  // carries the prose the device voice falls back to, so losing it offline would silence the
  // section entirely.
  const isData = url.pathname.endsWith("briefing.json") || url.pathname.endsWith("lessons.json") ||
                 url.pathname.includes("/archive/");
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
