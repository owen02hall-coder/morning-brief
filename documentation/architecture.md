---
title: Architecture
source_files: [scripts/, docs/, .github/workflows/briefing.yml]
entry_points: ["python -m scripts.build_briefing", "scripts/build_briefing.py:main"]
last_verified: 2026-06-16
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
  hour-gate (only the ~6am America/Denver run does work; the other no-ops)
  -> state.load()                          state/state.json
  -> market.get_market()                   FRED keyless CSV (S&P 500, Nasdaq Composite, VIX, 10-yr)
  -> news.get_news()                       RSS feeds (world, business, tech), per-feed isolation
  -> summarize.summarize()                 Gemini structured output (numbers injected as facts)
  -> assemble briefing dict
  -> write docs/briefing.json
            docs/archive/<date>.json
            docs/archive/index.json
            state/state.json (last_run rewritten -> daily renewing commit)
  -> notify.morning_ready() + health ping if degraded
  -> git commit + push (docs/ and state/)  --> GitHub Pages redeploys
PWA (docs/app.js): fetch briefing.json (network-first) -> render; archive + search; staleness banner
```

## Modules

- `scripts/config.py`: all tunables. Timezone, run hour, model id and fallback, news window, RSS
  feed lists, FRED series, paths, staleness threshold. No secrets.
- `scripts/build_briefing.py`: orchestrator and CLI. Hour-gate, flag handling, assembly, writing,
  archive index, top-level failure handling.
- `scripts/data/market.py`: the four headline numbers from FRED, recent-window fetch, last-two
  observations for value and day change. Each value may be None.
- `scripts/data/news.py`: RSS fetch and parse into world, business, tech candidate lists. Per-feed
  try/except, time-window cutoff, dedupe, per-bucket cap.
- `scripts/data/twelvedata.py`: a REST client. NOT used in v1. Staged for v2 breadth.
- `scripts/summarize.py`: Gemini call with a response schema. Numbers are passed as facts and the
  model writes only the prose. URLs are validated against the fetched set. Model and no-AI
  fallbacks. Returns (narrative, ok).
- `scripts/state.py`: load and save `state/state.json`. `last_run` is always rewritten.
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

Note: `market.ndx` is the Nasdaq Composite (FRED NASDAQCOM), labeled "Nasdaq" in the UI. Each
number carries its own `asof` date. FRED publishes with a short lag, so values are the latest
available close, not live or intraday. The UI shows the as-of date and the AI describes them as the
latest close.

## Entry points

- `python -m scripts.build_briefing` runs the daily flow with the hour-gate.
- `--force` runs real work now regardless of the hour (manual CI run).
- `--local` runs now and skips the hour-gate (dev).
- `--spine` prints market numbers and news counts, writes nothing.
- `--no-notify` skips the ntfy pushes.

## Scope

v1 (built) is the core briefing. The breadth and oversold-alert feature is deferred to v2. See
`tmp/ready-plans/2026-06-15-morning-briefing-pwa.md` for the v2 design and the reason for deferral
(free market-data rate limits prevent a daily 600-constituent pull).
