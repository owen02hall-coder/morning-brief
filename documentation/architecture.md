---
title: Architecture
source_files: [scripts/, docs/, .github/workflows/briefing.yml, .github/workflows/heartbeat.yml]
entry_points: ["python -m scripts.build_briefing", "scripts/build_briefing.py:main", "python -m scripts.heartbeat"]
last_verified: 2026-06-22
---

# Architecture

A free, single-user morning briefing. A scheduled job gathers market numbers and news, an AI
writes a short cited summary, the result is published as a static web app, and a push notification
is sent. Everything runs in the cloud so the user's devices can be off. Cost is zero on free tiers.

## Components

- Scheduler: a GitHub Actions workflow (`.github/workflows/briefing.yml`) runs daily on cron.
- Pipeline: a Python package (`scripts/`) that fetches data, summarizes, and writes output.
- Web app: a static PWA (`docs/`) served by GitHub Pages that renders the output.
- Notifications: ntfy delivers a morning push and a self-monitoring health ping.

## Data flow

```
GitHub Actions (cron, UTC) --> python -m scripts.build_briefing
  date-gate (build once/day: first cron that lands builds; if last_run == today the rest no-op)
  -> state.load()                          state/state.json
  -> market.get_market()                   Yahoo Finance chart API, keyless (S&P 500, Nasdaq Comp, VIX, 10-yr)
  -> news.get_news()                       RSS feeds (world, business, tech), per-feed isolation
  -> summarize.summarize()                 Gemini structured output (numbers injected as facts)
  -> assemble briefing dict
  -> write docs/briefing.json
            docs/archive/<date>.json
            docs/archive/index.json
            state/state.json (last_run + markets_last_ok; last_run rewritten daily -> renewing commit)
  -> notify.morning_ready() + health ping if degraded (escalates high-priority if markets blank >= MARKETS_STALE_DAYS)
  -> git commit + push (docs/ and state/)  --> GitHub Pages redeploys
PWA (docs/app.js): fetch briefing.json (network-first) -> render; archive + search; staleness banner

Heartbeat (independent cron): python -m scripts.heartbeat
  -> fetch LIVE docs/briefing.json from Pages -> ntfy + non-zero exit if older than HEARTBEAT_STALE_HOURS
```

## Modules

- `scripts/config.py`: all tunables. Timezone, model id and fallback, news window, RSS feed lists,
  Yahoo symbols, paths, staleness + heartbeat thresholds. No secrets.
- `scripts/build_briefing.py`: orchestrator and CLI. Date-gate, flag handling, assembly, writing,
  archive index, top-level failure handling.
- `scripts/heartbeat.py`: independent liveness check. Fetches the live Pages briefing and pings ntfy
  (and exits non-zero) if it is stale or unreachable. Run by `.github/workflows/heartbeat.yml`.
- `scripts/data/market.py`: the four headline numbers from Yahoo's chart API, recent-window fetch, last-two
  observations for value and day change. Each value may be None.
- `scripts/data/news.py`: RSS fetch and parse into world, business, tech candidate lists. Per-feed
  try/except, time-window cutoff, dedupe, per-bucket cap.
- `scripts/data/twelvedata.py`: a REST client. NOT used in v1. Staged for v2 breadth.
- `scripts/summarize.py`: Gemini call with a response schema. Numbers are passed as facts and the
  model writes only the prose. URLs are validated against the fetched set. `_clean_tldr` drops
  TL;DR fragments (keeps complete sentences) so a malformed model response cannot ship a broken
  headline. Model and no-AI fallbacks. Returns (narrative, ok).
- `scripts/state.py`: load and save `state/state.json` (`last_run`, `markets_last_ok`). `last_run`
  is always rewritten; `markets_last_ok` advances only on a day all four market numbers are present.
- `scripts/notify.py`: ntfy publish for the morning push and the health ping.

## Key design decisions

- Numbers come from data feeds, never from the model. The model explains them, it does not produce
  them. This is the accuracy guarantee.
- Source links are validated in code. Any item URL not in the fetched article set is dropped, so an
  invented citation cannot reach the output.
- The run degrades, it does not skip. A failed feed marks one section unavailable. A failed AI call
  falls back to a no-prose briefing of raw numbers and headlines. World news always ships if present.
- Staleness is age-based. The PWA shows a notice when the briefing is older than `STALE_HOURS`.
- The daily commit always changes `state.json` (last_run), which keeps the scheduled workflow from
  auto-disabling after 60 idle days.
- The archive needs an index. GitHub Pages cannot list a directory, so the pipeline writes
  `docs/archive/index.json` for the PWA to read.
- Failures must be loud, not silent. Three independent monitors cover the failure classes that have
  actually occurred: the build's own crash/degraded ntfy; a sustained market blackout escalating to
  high-priority after `MARKETS_STALE_DAYS` (a dead source degrades silently otherwise); and an
  independent heartbeat workflow checking the live page (catches a build that stopped or no-opped).

## briefing.json schema

```
generated_at : ISO datetime (America/Denver)
date         : YYYY-MM-DD
tldr         : list of up to 3 strings
market       : { sp500: {value, change, asof}, ndx: {value, change, asof}, why: str }
yield_10y    : { value, change, asof, why }
vix          : { value, change, asof, why }
tech         : list of { summary, source, url }
world        : list of { summary, source, url }
weekly_recap : string or null (Sundays only)
data_availability : map of section -> true/false or "ok"/"unavailable"
```

Note: `market.ndx` is the Nasdaq Composite (Yahoo `^IXIC`), labeled "Nasdaq" in the UI. Each
number carries its own `asof` date. Values are the latest daily close (last two closes give the
day-over-day change), not live or intraday. The UI shows the as-of date and the AI describes them as the
latest close.

## Entry points

- `python -m scripts.build_briefing` runs the daily flow with the once-per-day date-gate.
- `--force` bypasses the date-gate and builds now (manual CI run).
- `--local` bypasses the date-gate and builds now (dev).
- `--spine` prints market numbers and news counts, writes nothing.
- `--no-notify` skips the ntfy pushes.
- `python -m scripts.heartbeat` checks the live page freshness (run by its own workflow).

## Scope

v1 (built) is the core briefing. The breadth and oversold-alert feature is deferred to v2. See
`tmp/ready-plans/2026-06-15-morning-briefing-pwa.md` for the v2 design and the reason for deferral
(free market-data rate limits prevent a daily 600-constituent pull).
