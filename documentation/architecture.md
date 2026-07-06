---
title: Architecture
source_files: [scripts/, docs/, .github/workflows/]
entry_points: ["python -m scripts.build_briefing", "scripts/build_briefing.py:main", "python -m scripts.heartbeat", "python -m scripts.notify ready"]
last_verified: 2026-07-06
---

# Architecture

A free, single-user morning briefing. A scheduled job gathers market numbers and news, an AI
writes a short cited summary, the result is published as a static web app, and a push notification
is sent. Everything runs in the cloud so the user's devices can be off. Cost is zero on free tiers.

## Components

- Scheduler: a GitHub Actions workflow (`.github/workflows/briefing.yml`) runs daily on cron.
- Pipeline: a Python package (`scripts/`) that fetches data, summarizes, narrates, and writes output.
- Web app: a static PWA (`docs/`) served by GitHub Pages that renders the output, with a Listen
  player for the daily audio edition (on-device speech fallback).
- Notifications: ntfy delivers a post-publish "ready" push, breadth alerts (two tiers), and
  self-monitoring health pings.
- Guards: `shell-guard.yml` fails any push that changes the PWA shell without a service-worker
  CACHE bump; `data-smoke.yml` (dispatch-only) proves every data leg from a runner IP.

## Data flow

```
GitHub Actions (cron, UTC) --> python -m scripts.build_briefing
  date-gate (build once/day: first cron that lands builds; if last_run == today the rest no-op)
  -> state.load()                          state/state.json
  -> market.get_market()                   Yahoo Finance chart API, keyless (S&P 500, Nasdaq Comp, VIX, 10-yr)
  -> news.get_news()                       RSS feeds (world, business, tech), per-feed isolation
  -> breadth compute (TradingView scan ∩ Wikipedia constituents, S&P 500 + Nasdaq-100;
     per-index MIN_MATCH fail-close + last-good cache)
  -> summarize.summarize()                 Gemini structured output (numbers injected as facts)
  -> assemble briefing dict (incl. breadth block)
  -> write docs/briefing.json
            docs/archive/<date>.json
            docs/archive/index.json
            headline.txt                   (job-local handoff for the post-publish ready push)
  -> tts.generate()                        deterministic narration -> Gemini TTS -> audio.mp3 (lameenc, in-process)
  -> breadth alert eval (warning <40 one-shot / oversold <30 daily nag, per index) -> state
  -> state.save (last_run + markets_* + breadth state; last_run rewritten daily -> renewing commit)
  -> health pings if degraded/crashed; breadth alerts via ntfy
workflow: Publish audio edition            audio.mp3 -> docs/briefing-audio.mp3 + date manifest (only on success)
workflow: git commit + push (docs/, state/) --> GitHub Pages redeploys
workflow: Send ready push                  python -m scripts.notify ready — ONLY after git push succeeded
PWA (docs/app.js): fetch briefing.json (network-first) -> render; Listen player (mp3 when the
  manifest date matches, else chunked speechSynthesis); archive + search; staleness banner

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
- `scripts/data/constituents.py`: current S&P 500 (~503, linked ticker cell) and Nasdaq-100
  (~101, plain-text ticker cell) member lists from Wikipedia. stdlib regex parse, fail-closed on
  implausible counts — a biased breadth number must never ship silently.
- `scripts/breadth/percent_above_ma.py`: % of index members above their 200-day MA. ONE daily
  POST to TradingView's scanner (top `BREADTH_SCAN_LIMIT` US common stocks; the `type=stock`
  filter is load-bearing — without it ADR/fund rows displace ~90 S&P names), intersected with
  both constituent lists. Per-index `MIN_MATCH` gates. Validated vs published $S5TH / $NDTH.
- `scripts/tts.py`: the audio edition. Composes a deterministic drive-time narration (must-knows,
  S&P/Nasdaq percent moves only, tech, world — deliberately leaner than the page) and synthesizes
  it with Gemini TTS (`TTS_MODEL`/`TTS_VOICE`), encoding mp3 in-process with `lameenc` (the
  runner has no ffmpeg). Non-fatal end to end. Mirror narration changes in `docs/app.js`
  `speechText()`.
- `scripts/data/twelvedata.py`: a REST client. NOT used (v2 breadth shipped keyless via
  TradingView instead). Kept only as a possible future source.
- `scripts/summarize.py`: Gemini call with a response schema. Numbers are passed as facts and the
  model writes only the prose. URLs are validated against the fetched set. `_clean_tldr` drops
  TL;DR fragments (keeps complete sentences) so a malformed model response cannot ship a broken
  headline. Model and no-AI fallbacks. Returns (narrative, ok).
- `scripts/state.py`: load and save `state/state.json` (`last_run`, `markets_last_ok`,
  `markets_first_bad`, per-index `breadth` alert state, `breadth_last_good` cache). `last_run` is
  always rewritten; `markets_last_ok` advances only on a day all four market numbers are present;
  `markets_first_bad` anchors a blackout that began with no usable healthy baseline.
  `eval_breadth_alert` implements the two alert tiers per index: WARNING one-shot on falling
  below `BREADTH_WARN` (40, re-armed at 42) and OVERSOLD daily nag below `BREADTH_OVERSOLD` (30,
  clears at 33, EXTREME below 20) — both freshness-gated; oversold supersedes warning.
- `scripts/notify.py`: ntfy publish for the ready push, breadth alerts, and health pings. Also a
  CLI (`python -m scripts.notify ready`) the workflow calls AFTER `git push` succeeds, reading
  the headline the build wrote to `headline.txt` — so "ready" can never precede publication.

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
- Fail-closed over plausible-but-wrong. Breadth refuses to publish when constituent matching
  drops below MIN_MATCH (scan/shape drift); the audio manifest is written only alongside a real
  mp3 so the player can never bind stale audio to a new page; the "ready" push fires only after
  the publish leg succeeded.
- Recurring silent bug-classes get machine guards, not comments: `shell-guard.yml` fails a shell
  change without a sw.js CACHE bump (this class shipped broken once); workflows install with a
  CI-frozen `constraints.txt` and pin actions by commit SHA (the daily job holds a write token).
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
breadth      : { sp500: B, ndx100: B } where B = { value, asof, status, matched, stale }
               (status: oversold <30 | watch <40 | healthy >=40 | unavailable; value null when
               unavailable; stale=true when served from the last-good cache. Archives before
               2026-07-06 carry a legacy flat single-index shape, which the PWA still renders.)
tech         : list of { summary, source, url }
world        : list of { summary, source, url }
weekly_recap : string or null (Sundays only)
data_availability : map of section -> true/false or "ok"/"unavailable"
```

Companion files: `docs/briefing-audio.mp3` (the day's narration) + `docs/briefing-audio.json`
(`{date}` manifest — the player binds audio only when it matches the briefing's date).

Note: `market.ndx` is the Nasdaq Composite (Yahoo `^IXIC`), labeled "Nasdaq" in the UI. Each
number carries its own `asof` date. Values are the latest SETTLED daily close — a bar belonging to
a still-open session is dropped, never shipped as a close. `change` is the difference of the last
two settled closes, or `null` when only one settled close is available (the UI then shows the
level alone; the AI facts block says "change unavailable"). The UI shows the as-of date and the AI
describes the figures as the latest close.

## Entry points

- `python -m scripts.build_briefing` runs the daily flow with the once-per-day date-gate.
- `--force` bypasses the date-gate and builds now (manual CI run).
- `--local` bypasses the date-gate and builds now (dev).
- `--spine` prints market numbers and news counts, writes nothing.
- `--no-notify` skips the ntfy pushes.
- `python -m scripts.heartbeat` checks the live page freshness (run by its own workflow).
- `python -m scripts.notify ready` sends the post-publish ready push (workflow-only step).

## Scope

v1 (core briefing) and v2 (breadth + tiered oversold alerts, both indices; audio edition) are
built and live. The delivered v2 design (with deltas from the original plan) is archived at
`tmp/done-plans/2026-06-16-breadth-and-fresh-data.md`.
