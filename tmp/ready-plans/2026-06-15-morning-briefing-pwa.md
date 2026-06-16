# Plan: Personal Morning Briefing (PWA + GitHub Actions + Gemini)

## Goal

Build a free, single-user **morning briefing**: a daily GitHub Actions job pulls live market
data and fresh news, has Google's free-tier Gemini write a concise, cited, plain-text briefing,
publishes it to a GitHub Pages PWA the user reads on their phone, and sends an ntfy.sh push each
morning plus a daily nag-alert whenever market breadth is oversold. Breadth is a **dual gauge**:
a reliable primary (% of constituents above their 200-day moving average) plus, when computable,
the StockCharts-style Bullish Percent Index ($BPSPX / $BPNDX). Everything runs with the user's
laptop/phones off, at $0/month.

## Summary

- New greenfield repo: a Python data/summarize/notify pipeline (`scripts/`), a static PWA
  (`docs/`), and one scheduled GitHub Actions workflow.
- The pipeline has two cleanly separated paths: a **light path** (index levels, VIX, 10-yr yield
  + RSS news) that is reliable and reused by the AI summary; and a **heavy path** (compute breadth
  from ~600 constituent prices) that is isolated and gracefully degradable.
- **All market data comes from Twelve Data** (free tier, API key, works from CI). yfinance/Yahoo
  was rejected — it is IP-blocked from GitHub Actions runners.
- **Breadth is dual:** PRIMARY = % above 200-day MA (simple, reliable, drives the nag at <30);
  SECONDARY = Bullish Percent Index via Point & Figure (shown when computable, with its own <35
  indicator). If the secondary is off or data is short, the primary still carries the signal.
- Gemini (`gemini-2.5-flash`, free tier) turns the gathered data + fetched articles into a
  structured JSON briefing; the PWA renders `briefing.json`; ntfy delivers notifications.
- Accuracy comes from the plumbing: all numbers come from data feeds (never AI-invented), and the
  AI only summarizes articles fetched that morning and cites only those real URLs.

## Status & Scope (updated 2026-06-15 after /script proof)

Assumption tests were run against real services. Results:
- **PROVEN GREEN:** Gemini (`gemini-2.5-flash`, `response_mime_type+response_schema` config,
  `resp.parsed` valid); RSS feeds (11/11 alive, 232 fresh items/72h); Wikipedia constituents
  (503 / 101, header-matched); symbol normalization. Twelve Data API key is valid and returns
  real quotes.
- **BLOCKER FOUND:** Twelve Data free tier = **8 credits/minute (1 credit per symbol)**. A daily
  600-constituent breadth pull = ~75 min of throttled calls and ~600 of 800 daily credits —
  not viable/robust on the free tier.

**Scope decision (user-approved): ship the CORE briefing now; defer the breadth/oversold feature
to v2.**

- **v1 (build now):** TL;DR · Market (S&P 500 / Nasdaq + why) · 10-yr Treasury yield · VIX ·
  Emerging tech · World news · searchable archive · Sunday weekly recap · morning "ready" ntfy.
  Market headline numbers come from Twelve Data (4 symbols = 4 credits, comfortably within limits);
  news from RSS; write-up from Gemini. All three are proven.
- **v2 (fast-follow):** the breadth gauges (% above 200-day MA primary + BPI secondary) and the
  oversold nag-alert — once a **1-call-per-day whole-market data source** is proven (e.g. Polygon
  "grouped daily" aggregates). Until then, the PWA omits the breadth section (no "coming soon"
  placeholder noise) and no breadth nag fires.

All breadth-related content below (constituents/prices/percent_above_ma/bpi, the nag alert, the
breadth fields, Tasks touching them) is **v2 scope** and is NOT built in v1.

## Intent / Why

- The user wants a single simple "daily information upload" read in the morning: what the market
  did and why, an oversold-breadth nag, emerging tech, and globally significant world news — each a
  few sentences with a read-more link and a cited source.
- Must be free (Claude subscription only; no other spend), work when the user's laptop and phones
  are off, and be accurate/up-to-date (the user's #1 priority).
- What must remain true regardless of implementation details: numbers are never hallucinated;
  sources are real and cited; the briefing still ships (degraded) when a data source fails; no
  emojis anywhere; everything stays high-level "overall picture," not granular tracking.

## Source Artifacts

- Brief / intent artifact: `./tmp/briefs/2026-06-15-morning-briefing.md`
- Research dossier: inline in this plan (see All Needed Context); no separate dossier file.

## What

A daily briefing, top to bottom, rendered as a phone-installable PWA:

1. **TL;DR** — the 3 must-knows.
2. **Market** — what the S&P 500 / Nasdaq did and why (cited).
3. **10-year Treasury yield** — value + day move + one-line why.
4. **VIX** — value + one-line why.
5. **Breadth** — PRIMARY: % of S&P 500 / Nasdaq-100 stocks above their 200-day MA (oversold nag
   at < 30, extreme < 20); SECONDARY: $BPSPX / $BPNDX shown when computable (its own < 35 mark).
6. **Emerging tech** — a few cutting-edge items (cited).
7. **World news** — only globally significant events (cited).
8. **Read-more** per item; **archive** (with search) of past briefings; **Sunday weekly recap**.

### Success Criteria

- [ ] `python -m scripts.build_briefing --local --no-notify` produces a valid `docs/briefing.json`
      with all sections, real source URLs, and no emojis.
- [ ] The data spine CLI prints the four headline numbers + both breadth gauges. The ~600-ticker
      pull is proven to succeed **from inside a GitHub Actions runner** (Twelve Data, keyed) — not
      just locally — before the full pipeline is built.
- [ ] PRIMARY breadth (% above 200-day MA) is computed for both indices and drives the nag at < 30
      with anti-flicker (clears at ≥ 33); < 20 flagged "extreme."
- [ ] SECONDARY breadth (BPI) is shown when computable; if the P&F result is missing or its hand-
      validation against StockCharts (5–10 tickers, ≥2 near a signal flip) fails, the briefing still
      ships with the primary gauge and BPI marked unavailable. BPI is **never** the sole signal.
- [ ] Breadth carries a `prices_asof` date; the nag never fires/increments on prices older than
      ~2 trading days (no silent stale-data alert).
- [ ] Opening the GitHub Pages URL on a phone renders the briefing and is installable; when the
      briefing is older than ~28h it shows an age-based "couldn't refresh — last updated X" notice.
- [ ] Every rendered source link is one that was actually fetched (AI-invented URLs dropped in code).
- [ ] The scheduled workflow runs unattended (laptop off), commits `docs/briefing.json`, and sends
      an ntfy push with a tap-through to the Pages URL.
- [ ] When any single data source fails, that section reads "information not available" and the rest
      of the briefing (always including world news) still ships.
- [ ] Self-monitoring: an unhandled failure sends a high-priority "Briefing FAILED" ntfy (plus a
      workflow `if: failure()` backstop); a partial run sends a low-priority "degraded" ntfy — silent
      failures become loud.

## Verified Repo Truths

### Data / State

- Fact: The project directory is greenfield — no application code, not a git repository.
  Evidence: Environment context for `c:\Users\User\Desktop\AI CODE\News` ("Is a git repository:
  false"); only `tmp/briefs/` and `tmp/ready-plans/` exist.
  Implication: Everything is created new; there are no existing patterns/conventions to match, so
  the template's repo-anchor sections are intentionally sparse. The implementer must `git init`
  and create a GitHub repo as part of setup.
  Search Evidence: `Glob tmp/briefs/*.md` returned only the brief; no source files found.

## Locked Decisions

From the brief (settled; do not re-litigate):

- **Delivery = PWA** on GitHub Pages (not native app, not email/Telegram-only).
- **Engine = GitHub Actions scheduled workflow + Google Gemini free tier** (not Anthropic cloud
  routine, not local Task Scheduler, not an old phone, not a paid API).
- **Market data = Twelve Data free tier** (keyed, CI-reliable). yfinance/Yahoo rejected (IP-blocked
  from Actions runners); Stooq rejected (anti-bot wall); FRED keyless CSV is a 10-yr-yield fallback.
- **[DEFERRED TO v2] Breadth = DUAL gauge (user chose "do both"):** PRIMARY = % of constituents
  above their 200-day moving average per index (oversold < 30, anti-flicker clear at ≥ 33, extreme
  < 20); SECONDARY = $BPSPX / $BPNDX Bullish Percent Index via Point & Figure. NOT in v1 — the
  Twelve Data free tier (8 credits/min) can't pull 600 constituents daily; v2 needs a 1-call/day
  whole-market source (e.g. Polygon grouped-daily) proven via an assumption test first.
- **Notifications = ntfy.sh** — v1: the morning "ready" drop + the failure/degradation health ping.
  The breadth nag is v2 (ships with the breadth feature).
- **Archive includes simple client-side search** — a text filter over saved briefings.
- **Accuracy in the plumbing:** numbers from feeds only; AI summarizes only fetched articles and
  cites only those real URLs.
- **No emojis anywhere** (briefing, UI, notifications).
- **World news = globally significant only**, not granular/partisan US politics.
- **Sources = neutral, accurate, diversified mainstream**; no preferred/blocked outlets.
- **High-level overview only**; short few-sentence items + read-more.
- **Sections (v1):** TL;DR, market-why, 10-yr yield, VIX, emerging tech, world news; plus
  archive (searchable) + Sunday weekly recap. (Breadth section is v2.)
- **Run time:** ~6am America/Denver (Mountain, Utah).
- **No watchlist, no crypto, no economic calendar, no audio** in v1 (deferred).

Guardrails the implementation must not silently weaken: never invent numbers or source URLs;
never let a single failed feed abort the whole briefing; never serve stale data as if fresh; the
nag must always have a working primary gauge behind it.

## Known Mismatches / Assumptions

- Mismatch: The brief originally assumed Stooq, then yfinance, for free prices. Research (2026-06-15)
  found Stooq is behind an anti-bot wall and **yfinance is IP-blocked from GitHub Actions runners**
  (documented 429-on-first-call from datacenter IPs across yfinance 0.2.54–0.2.61, 2025).
  Repo Evidence: N/A (greenfield).
  Requirement Evidence: Brief "Free data sources (REVISED)" + research issues #2480/#2518/#2422.
  Planning Decision: Use **Twelve Data free tier** (800 credits/day, comma-batched, 1 credit/symbol)
  for the four headline numbers AND the ~600 constituent daily closes. FRED keyless CSV (`DGS10`) is
  a 10-yr-yield fallback only.
- Mismatch: Brief's originating trigger was BPSPX/BPNDX < 35. P&F replication is finicky and its
  accuracy near 35 is unproven.
  Planning Decision: Keep BPI as a SECONDARY gauge; the PRIMARY oversold signal is % above 200-day
  MA (< 30), which is simpler, standard, and reliable. User approved this "do both" split.
- Assumption: The user will create a free GitHub account, a Google AI Studio key (Gemini, billing
  disabled), a free Twelve Data API key, and pick an unguessable ntfy topic. Confirmed in discussion.
- Assumption: A public GitHub repo is acceptable (required for free Pages + unlimited Actions); the
  briefing JSON and Pages URL are world-readable. Accepted in brief (no personal data).
- To verify in implementation (not blocking): that S&P 500 / Nasdaq-100 **index levels** are
  available on the Twelve Data free tier (some index symbols are gated); if not, fall back to FRED
  `SP500` for the S&P level and derive the Nasdaq direction from constituents.

## Critical Codebase Anchors

- None (greenfield). External anchors are captured in All Needed Context below.

## All Needed Context

### Documentation & References

- External doc: Twelve Data API — https://support.twelvedata.com/en/articles/5203360-batch-api-requests
  and credits https://support.twelvedata.com/en/articles/5615854-credits
  Why: Primary market-data source, key via `TWELVEDATA_API_KEY`. 800 credits/day (resets 00:00 UTC),
  comma-separated `symbol` on `/time_series` and `/quote`, **1 credit per symbol**. ~604 credits/day
  (4 headline + ~600 constituents) fits, with thin headroom.
  Critical insight: works from CI (key-based, not IP-reputation-blocked like Yahoo). Seed ~250 days
  of history once via `/time_series?...&outputsize=250` (1 credit/symbol regardless of outputsize),
  then fetch the daily increment. Request split-adjusted closes for consistency. Handle 429/`code`
  errors with backoff. Verify free-tier availability of index symbols (SPX/NDX/VIX) at build time.
- External doc: % above moving average (breadth) — https://chartschool.stockcharts.com/table-of-contents/market-indicators/percent-above-moving-average
  Why: PRIMARY gauge definition + thresholds. % of index members trading above their 200-day SMA;
  50% = bull/bear pivot, **< 30% = oversold / market weakness, < 20% = extreme** (mirrors BPI < 35).
  Critical insight: trivial to compute (SMA compare per stock) — no Point & Figure needed; this is
  why it's the reliable primary.
- External doc: BPI + P&F methodology (SECONDARY) — https://chartschool.stockcharts.com/table-of-contents/market-indicators/bullish-percent-index-bpi
  and scaling https://chartschool.stockcharts.com/table-of-contents/chart-analysis/point-and-figure-charts/point-and-figure-basics/point-and-figure-scaling-and-timeframes
  Why: BPI = % of members on a P&F buy signal; traditional price-dependent box sizing + 3-box
  reversal + High/Low method.
  Critical insight: box size is recomputed per price level during forward column construction;
  validate the two highest-price bands against a live chart. BPI is secondary, so imperfection is
  tolerable — it never drives the nag alone.
- External doc: Gemini API — https://ai.google.dev/gemini-api/docs/structured-output and /text-generation
  Why: SDK `google-genai` (NOT `google-generativeai`); `genai.Client()` reads `GEMINI_API_KEY`;
  structured JSON via `response_mime_type="application/json"` + `response_schema=<pydantic model>`,
  read back via `resp.parsed`.
  Critical insight: Free tier (`gemini-2.5-flash`, 1M context, ~1,500 req/day) is far more than
  enough for 1–3 calls/day. **Free-tier inputs/outputs are used for training and may be
  human-reviewed** — acceptable (public news only); document in README; never feed secrets.
  Pin the SDK version; if `response_mime_type`/`response_schema` errors, fall back to the newer
  `response_format` config shape.
- External doc: GitHub Actions schedule — https://docs.github.com/en/actions/reference/events-that-trigger-workflows#schedule
  Why: cron is UTC-only; scheduled runs can be delayed at peak; public-repo scheduled workflows
  auto-disable after 60 days of no commits (the daily commit self-renews).
  Critical insight: commits made with the built-in `GITHUB_TOKEN` do not re-trigger workflows (no
  loop), and we trigger on `schedule` not `push` anyway.
- External doc: GitHub automatic token auth — https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication
  Why: `permissions: contents: write` + `actions/checkout@v4` lets `git push` work with no PAT.
- External doc: ntfy publish — https://docs.ntfy.sh/publish/
  Why: POST to `https://ntfy.sh/<topic>` with `Title`, `Priority`, `Tags`, `Click` headers.
  Critical insight: public topics — the topic name IS the password (read AND publish); use a long
  unguessable name, store it as an Actions secret, document the publish-spam vector.
- External doc: MDN PWA / service workers — https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps
  Why: Minimum installable PWA = `manifest.json` (name, start_url ".", display "standalone",
  192+512 icons) + a `sw.js` with a `fetch` handler.
  Critical insight: Use **relative** paths (works under `/<repo>/` on github.io); iOS has no auto
  install prompt (show an "Add to Home Screen" hint); iOS PWA push is unreliable — hence ntfy.

### Files Being Changed

```
morning-briefing/                         ← NEW repo (git init; public GitHub repo)
├── .github/
│   └── workflows/
│       └── briefing.yml                  ← NEW  scheduled daily workflow
├── scripts/
│   ├── __init__.py                       ← NEW  (package root; run as `python -m scripts.build_briefing`)
│   ├── build_briefing.py                 ← NEW  orchestrator entrypoint + CLI flags
│   ├── config.py                         ← NEW  thresholds, MA windows, RSS feeds, MODEL_ID + MODEL_FALLBACK
│   ├── state.py                          ← NEW  read/update state/state.json (alert state)
│   ├── data/
│   │   ├── __init__.py                   ← NEW
│   │   ├── twelvedata.py                 ← NEW  Twelve Data REST client (batched, backoff, credit-aware)
│   │   ├── market.py                     ← NEW  headline numbers SPX/NDX/VIX/10Y, one shared as-of date
│   │   ├── constituents.py               ← NEW  Wikipedia lists; header-matched, count-validated, fail-closed
│   │   ├── prices.py                     ← NEW  600 constituent daily closes (seed+increment); actions/cache; prices_asof
│   │   └── news.py                       ← NEW  RSS fetch/parse (feedparser), 48–72h window, per-feed isolation
│   ├── breadth/
│   │   ├── __init__.py                   ← NEW
│   │   ├── percent_above_ma.py           ← NEW  PRIMARY: % above 200-day (and 50-day) MA
│   │   └── bpi.py                        ← NEW  SECONDARY: P&F engine (per-step box size) + Bullish Percent Index
│   ├── summarize.py                      ← NEW  Gemini structured summarization; url post-validation; no-AI fallback; weekly recap
│   └── notify.py                         ← NEW  ntfy publish (morning + alert)
├── state/
│   └── state.json                        ← NEW (generated; alert state — committed for persistence, NOT served)
├── docs/                                 ← NEW  GitHub Pages root (Deploy from branch: main /docs)
│   ├── index.html                        ← NEW  PWA shell
│   ├── app.js                            ← NEW  fetch briefing.json (net-first), render, age-based staleness, archive list + search
│   ├── styles.css                        ← NEW  clean, no-emoji, light/dark
│   ├── manifest.json                     ← NEW
│   ├── sw.js                             ← NEW  service worker (shell cache-first, data net-first)
│   ├── icon-192.png / icon-512.png / icon-512-maskable.png  ← NEW
│   ├── .nojekyll                         ← NEW
│   ├── briefing.json                     ← NEW (generated daily; the only served data)
│   └── archive/
│       └── YYYY-MM-DD.json               ← NEW (generated; one per working run)
├── requirements.txt                      ← NEW  google-genai (pinned), requests, feedparser, pandas, lxml, pyarrow, tzdata
├── .gitignore                            ← NEW
└── README.md                             ← NEW  one-time setup (accounts, secrets, Pages, ntfy, data-privacy + publish-spam notes)

# NOTE: the 600-ticker price cache is NOT committed — it lives in GitHub Actions cache
# (actions/cache@v4) for warm-start, so git history stays small. Only docs/ + state/ are committed.
# No yfinance dependency — Twelve Data is a plain REST API hit via `requests`.
```

### Known Gotchas & Library Quirks

- **Use Twelve Data, NOT yfinance.** yfinance is IP-blocked from GitHub Actions runners (429 on the
  first call from datacenter IPs; not fixable with backoff/impersonation). Twelve Data is key-based
  and works from CI. Still: **prove a ~600-symbol batched pull from inside an Actions runner before
  building the pipeline** (smoke job), and handle 429/`code` error bodies with exponential backoff.
- **Twelve Data credit budget is tight.** 800 credits/day; 4 headline + ~600 constituents ≈ 604/day,
  leaving ~200 headroom. Batch with comma-separated symbols; don't make redundant calls. The one-time
  ~250-day history seed is also ~600 credits (outputsize doesn't add credits) so it fits in one day.
  Verify free-tier index-symbol availability (SPX/NDX/VIX) early; fall back to FRED `SP500` + a
  constituent-derived Nasdaq direction if indices are gated.
- **Request split-adjusted closes** (consistent across history); the % above 200-day MA gauge is
  robust to minor adjustment differences, but the P&F secondary is price-level sensitive so keep
  adjustment consistent for it too.
- **Warm-start cache via `actions/cache@v4`, NOT committed to git.** Committing a 600-ticker×250-day
  parquet rewrites a multi-MB blob into git history daily → unbounded bloat. Use the Actions cache
  (regenerable; eviction forces a re-seed). Make cache writes **atomic** (temp → validate per-ticker
  row counts/last-date → replace) so a partial/429'd pull can't poison the warm cache.
- **Breadth freshness gate.** Breadth functions return a `prices_asof` date. The nag must NOT
  increment or re-fire a high-priority alert on prices older than ~2 trading days (weekend / holiday /
  fallback) — otherwise a single stale value spams daily. On stale reuse, suppress or send at most a
  low-priority reminder.
- **Symbol mapping:** Wikipedia uses `BRK.B`/`BF.B`; Twelve Data wants the dotted or dashed form per
  its convention — normalize and verify a couple of class-share tickers resolve.
- **Wikipedia is brittle — fail closed.** Send a descriptive `User-Agent`; identify the symbol column
  **by header name** (not positional index); assert the row count is plausible (~500 / ~100) and
  nonzero, else mark breadth **unavailable** rather than computing over a truncated/garbage universe.
  (Same UA need for all RSS fetches.)
- **MIN_HISTORY for the gauges.** % above 200-day MA needs ≥200 daily closes per ticker; exclude
  tickers with insufficient history from that index's denominator (don't count them as "below").
  P&F needs only enough bars to form ~3 columns. Note denominator differences are a small source of
  drift vs StockCharts near the threshold.
- **Gemini structured output needs code-level guards.** `resp.parsed` can be `None` (schema coercion
  failure / safety truncation) — handle it (retry once, then degrade). Enforce "cite only fetched
  URLs" **in code**: post-validate every `Item.url` against the set passed in; drop/blank any that
  aren't. A prompt instruction is a label, not a mechanism.
- **Gemini total-failure fallback.** If Gemini 5xx/429s past backoff or returns unusable output,
  still ship a no-AI `briefing.json` (raw numbers + headline list with real URLs, no prose) and set
  `data_availability.summary = "unavailable"` — never skip a day.
- **Gemini free-tier trains on inputs** — public news only, document in README, never feed secrets.
  Keep the key on a billing-disabled project (enabling billing removes the free tier). Centralize
  `MODEL_ID` (+ `MODEL_FALLBACK`) in `config.py`; document the fallback (model ids move).
- **GitHub cron is UTC + delayed at peak.** Two crons (`0 12` and `0 13` UTC) bracket 6am Denver
  across DST; Python early-exits unless `zoneinfo("America/Denver")` hour == 6. The no-op run must
  exit **before any commit/notify/state write** (no duplicate push). Add `tzdata` to requirements
  (Windows/minimal Pythons raise `ZoneInfoNotFoundError` without it).
- **Always produce a daily renewing commit.** `state/state.json` must always rewrite `last_run` to
  today and be staged, so a market-holiday "nothing changed" day still commits and the 60-day
  scheduled-workflow auto-disable never trips. Use the built-in `GITHUB_TOKEN` (no PAT → no loop).
- **Set a job `timeout-minutes`** and per-request timeouts so a hung data pull degrades-to-cache
  instead of stalling the run (and missing the morning push).
- **Cold start:** seed defaults when `state/state.json` is absent; run the one-time ~250-day seed
  locally to prime the cache; the first Sunday recap tolerates < 7 archive files.
- **Service worker caching can serve a stale shell** — bump `CACHE` version on shell changes; fetch
  `briefing.json` **network-first** so the freshest edition shows when online.
- **Staleness is age-based, not calendar-based.** The PWA shows "couldn't refresh — last updated X"
  when `generated_at` is older than ~28h. Always render the human "last updated <timestamp>."
- **iOS**: no `beforeinstallprompt`; show a manual "Add to Home Screen" hint; do not rely on PWA push.

## Delta Design

### Data / State Changes

Existing:
- None (greenfield).

Change:
- `state/state.json` (NOT in `docs/`): persisted alert state per index for BOTH gauges, e.g.
  `{ "pct200_spx": {"in_alert": false, "last_value": 58.0, "last_asof": "...", "nag_days": 0},
  "pct200_ndx": {...}, "bpspx": {...}, "bpndx": {...}, "last_run": "2026-06-15" }`.
- Price history cache in `actions/cache@v4` (not git): 600 constituents, ~250 daily closes, atomic.
- `docs/briefing.json`: today's rendered briefing (see Data Models). `docs/archive/<date>.json`:
  immutable daily copies for the archive (searchable) + weekly recap input.

Why:
- `docs/` stays purely the public surface; state persists via a small committed file; the heavy
  price cache uses the native CI cache primitive (no git-history bloat).

Risks:
- Twelve Data daily credit headroom is thin (~200 spare). Mitigate: batch, no redundant calls,
  cache history and fetch only the increment.

### Execution / Control Flow

Existing:
- None.

Change:
- One scheduled workflow → runs `python -m scripts.build_briefing`, which orchestrates: hour-gate →
  state load → light path (Twelve Data headline numbers + RSS) → heavy path (constituents → prices →
  % above MA [primary] + BPI [secondary], degradable) → alert logic (primary-driven, freshness-gated)
  → Gemini summarize → write JSON + archive + state → ntfy → commit/push.

Why:
- Linear single-process pipeline is simplest for a once-daily job; light/heavy separation + dual
  breadth keep a working oversold signal independent of the fragile P&F computation.

Risks:
- A single uncaught exception aborts the run. Mitigate: wrap each section in try/except, collect a
  `data_availability` map, only abort on truly nothing-to-ship.

### User-Facing / Operator-Facing Surface

Existing:
- None.

Change:
- PWA (`docs/`) renders `briefing.json` into clean, no-emoji sections with expandable read-more and
  links; searchable archive; age-based staleness banner; iOS install hint.

Why / Risks:
- Static client + JSON data = zero hosting cost, offline-capable, installable. Stale-serving guarded
  by the age-based client check.

### External / Operational Surface

Existing:
- None.

Change:
- GitHub Actions (cron), GitHub Pages (serve), Twelve Data/Wikipedia/RSS (read), Gemini (summarize),
  ntfy (push). Secrets: `TWELVEDATA_API_KEY`, `GEMINI_API_KEY`, `NTFY_TOPIC`.

Why / Risks:
- All free tiers; document rate-limit/backoff handling, per-source isolation, and the ntfy
  publish-spam vector.

## Implementation Blueprint

### Architecture Overview

```
GitHub Actions (cron 12:00 & 13:00 UTC; gate: Denver hour == 6, else exit before side effects)
  └─ python -m scripts.build_briefing
       state = load(state/state.json)                          # seed defaults on cold start
       # LIGHT PATH (reliable; feeds the AI summary)
       market = twelvedata_reads(SPX, NDX, VIX, 10Y)           # one shared as-of date (FRED 10Y fallback)
       news   = rss_fetch(world, business, tech)               # per-feed try/except, 48-72h
       # HEAVY PATH (isolated; degradable)
       try:
         members = wikipedia(SP500, NDX)                        # header-matched, count-validated, fail-closed
         closes, prices_asof = update_cache(members)            # Twelve Data batched + backoff + actions/cache
         pct_spx, pct_ndx = pct_above_ma(closes, SP500, 200), pct_above_ma(closes, NDX, 200)   # PRIMARY
         bpspx, bpndx     = bpi(closes, SP500), bpi(closes, NDX)                                # SECONDARY (best-effort)
       except: breadth = UNAVAILABLE
       # ALERT (primary-driven, freshness-gated)
       alerts, state = eval_alerts(pct_spx, pct_ndx, prices_asof, state)   # <30 alert+nag; clear >=33; extreme <20
       # SUMMARIZE (numbers passed in as facts; AI writes only the "why"; URLs post-validated)
       briefing = gemini_summarize(market, news, breadth, is_sunday)
       write(docs/briefing.json); append(docs/archive/<date>.json); write(state/state.json)
       # NOTIFY
       ntfy(morning_ready, click=PAGES_URL); for a in alerts: ntfy(a, priority=high)
       if any_section_degraded: notify_health("degraded: " + unavailable_sections, priority=low)
  # (top-level try/except around the whole run → notify_health("Briefing FAILED", priority=high); exit 1)
  └─ git add docs/ state/ && commit && push    # GITHUB_TOKEN; updates Pages
  # workflow backstop: a final `if: failure()` step curls ntfy so even a crash before notify pings you
PWA (docs/): fetch briefing.json (network-first) → render; if generated_at older than ~28h → staleness banner
```

### Key Pseudocode

```python
# breadth/percent_above_ma.py — PRIMARY gauge (simple, reliable; drives the nag)
def pct_above_ma(closes_by_ticker, members, window=200):
    above = total = 0
    for t in members:
        closes = closes_by_ticker.get(t)
        if closes is None or len(closes) < window: continue     # insufficient history → exclude
        sma = mean(closes[-window:])
        total += 1
        if closes[-1] > sma: above += 1
    return round(100 * above / total, 1) if total else None      # None → unavailable
```

```python
# breadth/bpi.py — SECONDARY gauge (best-effort; never the sole signal)
def pnf_signal(highs, lows):
    # box size recomputed PER STEP from the price at that step during forward column construction
    # (NOT one box size from today's price). Worked example: a stock $24 -> $26 crosses the $25
    # boundary, so boxes use the band size appropriate to each tested price level.
    # build columns with High/Low + 3-box reversal; snap to box boundaries; walk columns; the most
    # recent of {double-top breakout = BUY} vs {double-bottom breakdown = SELL} sets current state;
    # "indeterminate" if <3 columns. bullish_percent = 100 * buys / (buys+sells).
    ...
```

```python
# state.py — primary-driven alert with anti-flicker hysteresis + freshness gate
# Oversold ON below 30, latched until recovery to >= 33; extreme flag < 20.
def eval_index_alert(pct_value, prices_asof, st, today_trading_date):
    if pct_value is None: return None, st                        # primary unavailable → no change
    stale = trading_days_between(prices_asof, today_trading_date) > 2
    if pct_value < 30:
        if stale:                                                # don't spam on stale prices
            return None, {**st, "in_alert": True, "last_value": pct_value, "last_asof": prices_asof}
        nag = st["nag_days"] + 1
        extreme = " (extreme)" if pct_value < 20 else ""
        st = {**st, "in_alert": True, "nag_days": nag, "last_value": pct_value, "last_asof": prices_asof}
        return f"{pct_value}% above 200-day MA — oversold{extreme}, day {nag}", st   # high priority
    if st["in_alert"] and pct_value < 33:
        return None, {**st, "last_value": pct_value, "last_asof": prices_asof}        # latched watch
    return None, {**st, "in_alert": False, "nag_days": 0, "last_value": pct_value, "last_asof": prices_asof}
```

```python
# summarize.py — grounded, cited, no-emoji structured output
SYSTEM = ("You are a precise financial/news editor. Use ONLY the provided data and articles. "
          "Cite ONLY URLs present in the input; never invent a source or a number. Plain "
          "professional text, NO emojis. Each item a few sentences. World news: only globally "
          "significant events, not granular partisan US politics. Neutral tone.")
# numbers (MarketNumber + breadth) passed as FACTS; model writes only the 'why'. articles passed as
# [{title, source, url, summary}]. response_schema = Briefing; read resp.parsed (handle None).
# AFTER parse: drop any Item whose url not in the fetched URL set. Sunday: fill weekly_recap from
# the last <=7 archive/*.json. On Gemini failure: emit no-AI numbers+headlines briefing.
```

### Data Models and Structure

```python
# pydantic models. AI fills only prose ("why"); authoritative NUMBERS live in separate fields
# populated directly from the feed and rendered from there — the model can't fumble a number in prose.
class Item(BaseModel):
    summary: str
    source: str
    url: str                # post-validated in code against the fetched URL set; dropped if absent

class MarketNumber(BaseModel):
    value: float            # from feed, NOT the model
    change: float           # day-over-day, from feed
    asof: str               # trading date the value belongs to
    why: str                # model-written explanation only

class Briefing(BaseModel):
    generated_at: str
    date: str
    tldr: conlist(str, max_length=3)   # enforced ≤3 (also truncated in code)
    market: dict            # {sp500: MarketNumber, ndx: MarketNumber, why: Item}
    yield_10y: MarketNumber
    vix: MarketNumber
    breadth: dict           # { pct200: {spx: float|null, ndx: float|null},
                            #   pct50:  {spx: float|null, ndx: float|null},   # optional
                            #   bpi:    {bpspx: float|null, bpndx: float|null},
                            #   prices_asof: str|null,
                            #   status: "ok|watch|alert|unavailable", note: str }
    tech: list[Item]
    world: list[Item]
    weekly_recap: str | None
    data_availability: dict
```

```json
// state/state.json  (committed for persistence, NOT served on Pages)
{ "pct200_spx": {"in_alert": false, "last_value": 58.0, "last_asof": "2026-06-12", "nag_days": 0},
  "pct200_ndx": {"in_alert": false, "last_value": 61.0, "last_asof": "2026-06-12", "nag_days": 0},
  "bpspx": {"last_value": 41.2, "last_asof": "2026-06-12"},
  "bpndx": {"last_value": 55.0, "last_asof": "2026-06-12"},
  "last_run": "2026-06-15" }    // last_run always rewritten to today → guarantees a daily commit
```

### Tasks (in implementation order)

Task 1 — Repo scaffold:
Goal: Buildable skeleton + dependency pinning.
Files: CREATE `requirements.txt` (google-genai PINNED, requests, feedparser, pandas, lxml, pyarrow,
  tzdata — NO yfinance), `.gitignore`, `scripts/config.py` (MA_WINDOWS=[200,50], OVERSOLD=30 /
  CLEAR=33 / EXTREME=20, BPI_MARK=35, MIN_HISTORY, RSS feed lists, `MODEL_ID="gemini-2.5-flash"` +
  `MODEL_FALLBACK`, NEWS_WINDOW_HOURS=72, STALE_TRADING_DAYS=2, PAGES_URL placeholder), all
  `__init__.py`s.
Gotchas: pin google-genai exactly; canonical run is `python -m scripts.build_briefing` (imports are
  `scripts.data.market` etc.).
Definition of done: `pip install -r requirements.txt` succeeds; `python -c "import scripts.config"` works.

Task 2 — Data spine (the de-risk step; matches brief's "one thing to do first"):
Goal: Print the four headline numbers + both breadth gauges; PROVE the 600-symbol pull from a runner.
Files: CREATE `scripts/data/twelvedata.py` (REST client: batched comma-separated symbols, backoff on
  429/`code`, credit-aware), `scripts/data/market.py` (SPX/NDX/VIX/10Y, assert one shared as-of date;
  FRED `DGS10` 10Y fallback), `scripts/data/constituents.py` (Wikipedia; column-by-header,
  count-validated ~500/~100, fail-closed), `scripts/data/prices.py` (600 constituent closes: one-time
  ~250-day seed + daily increment; atomic actions/cache; returns `prices_asof`),
  `scripts/breadth/percent_above_ma.py` (PRIMARY), `scripts/breadth/bpi.py` (SECONDARY, best-effort),
  and a `--spine` CLI in `build_briefing.py`.
Gotchas: **first prove a ~600-symbol batched Twelve Data pull succeeds from inside a GitHub Actions
  runner** (workflow_dispatch smoke job) and fits the credit budget, before relying on it; verify
  index-symbol availability on free tier; split-adjusted closes; exclude insufficient-history tickers;
  seed history once locally.
Definition of done: `python -m scripts.build_briefing --spine` prints SPX/NDX/VIX/10Y + % above
  200-day MA (both indices) + BPSPX/BPNDX; a runner smoke job pulls 600 symbols within credits;
  PRIMARY gauge is trusted; SECONDARY BPI hand-validated vs StockCharts on 5–10 tickers incl. ≥2
  near a flip — if BPI fails validation it is marked unavailable, NOT blocking (primary still ships).

Task 3 — News + summarization:
Goal: Produce a full `docs/briefing.json` locally.
Files: CREATE `scripts/data/news.py` (feedparser, per-feed try/except, 48–72h window, dedupe by
  normalized title/URL, UA, cap candidate count), `scripts/summarize.py` (Gemini structured output;
  no-emoji + globally-significant-only system prompt; **post-validate every Item.url against the
  fetched set, drop invalid**; handle `resp.parsed is None`; **no-AI fallback** = raw numbers +
  headlines; truncate tldr to 3; Sunday recap tolerant of <7 archive days), wire the pipeline (minus
  notify/commit) into `build_briefing.py`; always write `docs/archive/<date>.json` on a working run.
Gotchas: structured-output field names (`response_mime_type`/`response_schema`, fallback to
  `response_format` — verify against pinned SDK); numbers come from feed fields, model writes only
  the "why"; never let the summarizer being down skip the day.
Definition of done: local run writes a valid `briefing.json` with all sections, only real fetched
  URLs, no emoji; killing the Gemini call still ships a degraded numbers+headlines briefing.

Task 4 — PWA:
Goal: Installable phone-readable UI rendering the briefing.
Files: CREATE `docs/index.html`, `docs/app.js` (network-first fetch of briefing.json, render sections,
  render numbers from MarketNumber fields, show both breadth gauges, expandable read-more, **archive
  list + simple client-side text-filter search**, **age-based staleness banner** (>~28h), always show
  "last updated <timestamp>"), `docs/styles.css` (clean light/dark, no emoji), `docs/manifest.json`
  (relative paths), `docs/sw.js` (shell cache-first, data net-first), icons (192/512/maskable),
  `.nojekyll`.
Gotchas: relative paths for github.io subpath; bump SW CACHE version on shell change; iOS install
  hint; staleness is age-based.
Definition of done: opening the site renders a sample briefing.json; archive search filters; stale
  sample shows the age banner; devtools shows installable PWA criteria met; no emoji anywhere.

Task 5 — State + notifications + alert logic:
Goal: Persisted primary-driven nag-alert + ntfy delivery + self-monitoring health ping.
Files: CREATE `scripts/state.py` (load/update `state/state.json`; seed defaults on cold start; always
  rewrite `last_run`), `scripts/notify.py` (ntfy POST: morning ready w/ Click=PAGES_URL; per-index
  alert at high priority; **`notify_health(...)` for failure/degradation**); wire alert eval + notify
  into the pipeline.
Gotchas: alert is driven by the PRIMARY gauge (% above 200-day MA): ON <30, latched until ≥33, no
  spam in 30–33, extreme flag <20; **freshness gate** (no nag on prices >2 trading days old); breadth
  unavailable → no alert state change; topic from `NTFY_TOPIC` env (secret), never client-side.
Health-check (self-monitoring): wrap the orchestrator in a top-level try/except — on an unhandled
  failure send a high-priority "Briefing FAILED today" ntfy (then exit non-zero); on a partial run
  send a low-priority "Briefing degraded: <sections unavailable>" ntfy. Use the same `NTFY_TOPIC`
  (distinct title/priority) so silent failures become loud. (A separate `NTFY_HEALTH_TOPIC` is
  optional if the user wants to split alerts from the daily read.)
Definition of done: a forced sub-30 primary value triggers a high-priority alert ntfy and increments
  nag_days; an oscillating 29.5/30.5/29.8 sequence does NOT flap (latched until ≥33); a stale
  prices_asof suppresses the nag; morning "ready" ntfy received with working tap-through; a forced
  crash sends a "FAILED" health ntfy; a forced section-degradation sends a "degraded" health ntfy.

Task 6 — GitHub Actions workflow + Pages + README:
Goal: Unattended daily run, commit, deploy, documented setup.
Files: CREATE `.github/workflows/briefing.yml` (two crons 12:00/13:00 UTC; `workflow_dispatch` only,
  NO `pull_request`; `permissions: contents: write`; `timeout-minutes`; checkout@v4 + setup-python;
  **actions/cache@v4 for the price cache**; pip install; run `python -m scripts.build_briefing` with
  `TWELVEDATA_API_KEY`/`GEMINI_API_KEY`/`NTFY_TOPIC` env from secrets; the no-op (wrong-hour) run
  exits before any commit/notify; **a final `if: failure()` step curls ntfy as a crash backstop**;
  commit `docs/` + `state/` only with GITHUB_TOKEN), `README.md`
  (create PUBLIC repo, set Pages = Deploy from branch main /docs, add the three secrets, create the
  Twelve Data + Gemini keys [Gemini on a billing-DISABLED project] + document MODEL_FALLBACK, choose
  an unguessable ntfy topic + note it grants read AND publish, subscribe ntfy app, Add-to-Home-Screen
  steps, free-tier data-privacy note, one-time local cache-seed step).
Gotchas: Denver hour-gate in Python (needs tzdata); `state/state.json` always rewrites last_run so
  there is always a daily renewing commit (avoids 60-day auto-disable) even on holidays;
  `git diff --staged --quiet || git commit`; no PAT (avoids loop).
Definition of done: `workflow_dispatch` run completes green, commits briefing.json + state.json,
  Pages updates, ntfy received — laptop off; the second daily cron run no-ops cleanly.

### Integration Points

- Data sources: **Twelve Data** (keyed) for SPX/NDX/VIX/10Y + ~600 constituent closes; Wikipedia
  constituent tables (fail-closed); RSS feeds (BBC World, Al Jazeera, Guardian, NPR; MarketWatch,
  Yahoo Finance, CNBC; Ars Technica, The Verge, MIT Tech Review, Hacker News). FRED `DGS10` = 10Y
  fallback only.
- AI: Gemini `generateContent` via `google-genai`, key from `GEMINI_API_KEY`.
- Notifications: `https://ntfy.sh/<NTFY_TOPIC>`.
- Hosting/cron: GitHub Actions (`on: schedule`) + GitHub Pages (branch `main`, folder `/docs`).
- Secrets/env: `TWELVEDATA_API_KEY`, `GEMINI_API_KEY`, `NTFY_TOPIC`.

## Validation

```bash
# Python syntax + import sanity (no npm in this project)
python -m py_compile $(git ls-files 'scripts/**/*.py')
python -c "import scripts.config"
ruff check scripts/ || true   # if available

# End-to-end local dry run (no commit, no notify):
python -m scripts.build_briefing --spine               # prints headline numbers + both breadth gauges
python -m scripts.build_briefing --local --no-notify   # writes docs/briefing.json only
```

### Manual Checks

- Scenario: Run `--spine`; confirm % above 200-day MA looks sane (0–100, pivot ~50) for both
  indices; spot-check 5–10 tickers' P&F state vs StockCharts for the secondary BPI.
- Scenario: Force a primary value below 30. Expected: high-priority alert ntfy, `nag_days`
  increments across runs, clears at ≥33; values 30–33 don't flap.
- Scenario: Disable RSS only. Expected: world section "information not available" but briefing still
  ships with market + breadth.
- Scenario: Skip a day's run. Expected: PWA shows age-based "couldn't refresh — last updated <date>".
- Scenario: Open Pages URL on iPhone + Android. Expected: renders; iOS install hint; installable on
  Android; archive search works; no emojis anywhere.

## Open Questions

- None blocking. Validate during implementation (not blockers): Twelve Data free-tier index-symbol
  availability (SPX/NDX/VIX) + that a 600-symbol pull fits the daily credit budget from a runner
  (Task-2 hard gate); the two highest-price P&F box-size bands vs a live chart (secondary only); the
  exact Gemini structured-output config field names for the pinned SDK.

## Reconciliation Notes

### Review pass 1 (two plan-reviewers + value-critic + meta-pass)
- Real hysteresis + `prices_asof` freshness gate; "real source links" enforced in code; numbers in
  dedicated feed fields; no-AI degraded fallback; actions/cache (not committed); age-based staleness;
  always-write archive + cold-start; 48–72h news; fail-closed Wikipedia; job timeout; canonical
  `scripts` package; state moved out of public `docs/`; archive search; tldr truncation; model
  fallback; tzdata.

### Review pass 2 (confidence pass — research-driven)
- **Dropped yfinance entirely** — documented to be IP-blocked from GitHub Actions runners (would
  have broken the breadth feature). **Adopted Twelve Data** (keyed, CI-reliable) for all market data.
- **Breadth is now dual:** PRIMARY = % above 200-day MA (simple, reliable, drives the nag at <30 with
  anti-flicker clear at ≥33, extreme <20); SECONDARY = BPSPX/BPNDX via P&F (best-effort, own <35
  mark, never the sole signal). This removes the two biggest risks (yfinance-from-CI + P&F accuracy)
  from the critical path. Raised confidence ~7 → ~8.5.
- Added history seeding (~250 days, one-time local), Twelve Data credit-budget handling, and FRED
  `DGS10` as a 10Y fallback. `TWELVEDATA_API_KEY` added as a secret.

## Deprecated / Removed Code

- None (greenfield). (yfinance was removed from the design before any code existed.)

## Final Validation Checklist

- [ ] `python -m py_compile` clean over `scripts/`
- [ ] `--spine` prints headline numbers + both breadth gauges; 600-symbol pull proven from a runner
- [ ] PRIMARY breadth drives the nag (<30, clear ≥33, extreme <20); SECONDARY BPI best-effort only
- [ ] `briefing.json` has all sections, real cited URLs, zero emojis; no-AI fallback works
- [ ] Per-source failures degrade to "information not available"; world news always ships
- [ ] PWA installable on iOS + Android; age-based staleness banner + archive search work
- [ ] Freshness gate blocks nags on prices >2 trading days old; state persists; daily renewing commit
- [ ] Scheduled workflow runs unattended, commits, deploys, notifies; second cron no-ops
- [ ] README covers all setup (3 secrets, Pages, ntfy, seeding) + data-privacy + publish-spam notes
- [ ] No secrets committed; Gemini key on a billing-disabled Google project

## Anti-Patterns to Avoid

- Don't use yfinance from CI (IP-blocked) — use Twelve Data.
- Don't let the AI invent numbers or source URLs — inject numbers as facts, post-validate URLs in code.
- Don't let one failed feed/source abort the whole run — isolate with try/except per source.
- Don't let the BPI secondary block or drive the alert alone — the primary gauge is the signal.
- Don't serve stale data silently — age-based "last updated"; freshness-gate the nag.
- Don't commit the price cache (git bloat) — use actions/cache; atomic writes.
- Don't force insufficient-history tickers into the denominator.
- Don't use a PAT to push (loop risk) — use the built-in `GITHUB_TOKEN`.
- Don't put any emoji in briefing, UI, notifications, or commit messages.
- Don't enable billing on the Gemini key's Google project (removes the free tier).

## Criticer Notes

1. **[honest assessment — the data round-trip is the silent failure point]** The heavy path rests on
   pulling ~600 tickers daily from CI. yfinance is IP-blocked from Actions; resolved by switching to
   Twelve Data (keyed). Still prove the 600-symbol pull + credit budget from a runner, not just the
   dev laptop, and fail loudly (not to permanently-stale cache) if it can't refresh.
2. **[biggest gap — price-data freshness must feed the alert]** Resolved: breadth carries
   `prices_asof`; the nag is freshness-gated (no fire on prices >2 trading days old).
3. **[cheap win — enforce URL grounding in code]** Resolved: post-validate every Item.url against the
   fetched set; drop invented links.
4. **[premise check — BPI accuracy was unproven]** Resolved structurally: BPI is now SECONDARY; the
   PRIMARY % above 200-day MA is simple and reliable and carries the oversold signal, so the project
   no longer hinges on replicating StockCharts' P&F exactly.
5. **[over-built — committing the price cache]** Resolved: cache moved to actions/cache, not git.
