---
title: Documentation Index
source_files: [documentation/]
entry_points: [documentation/architecture.md, documentation/integrations.md, documentation/operations.md]
last_verified: 2026-09-09
---

# Documentation

Developer documentation for the Morning Briefing project. The user-facing setup guide is the
top-level `README.md`. These files cover how the system is built and run.

Note: the project's `docs/` folder is the GitHub Pages web root (it serves the PWA), not a
documentation folder. Developer docs live here in `documentation/` to avoid polluting the live site.
Anything written into `docs/` is published.

## Files

- `architecture.md` — system overview, data flow, the module-by-module map, key design decisions and
  the reasons behind them, the `briefing.json` and `lessons.json` schemas, and the CLI entry points.
- `integrations.md` — every external service (Yahoo Finance for the headline numbers and the
  watchlist pulse, the TradingView scanner and Wikipedia for breadth, Gemini for the summary and
  the audio, ntfy, RSS, the Federal Register, the Utah Legislature, Freddie Mac PMMS, the Wikipedia
  action API behind Alphabet Soup, GitHub Pages and Actions), what each is used for, where it is
  invoked, its per-build request budget, and the env var names. Also the probed-dead source list, so
  a dead end is not re-explored.
- `operations.md` — scheduling and DST, one-time deployment, runtime behavior, monitoring and its
  four alarms, run-state keys and their writers, failure modes and recovery, regression tests, and
  cost.

## Start here if you want to...

- Understand how the briefing is produced end to end: `architecture.md`.
- Add or swap a data source, or change an API key: `integrations.md`.
- Deploy it, change the schedule, or debug a failed run: `operations.md`.
- Change anything that is SPOKEN: `operations.md` → Regression tests. The narration is implemented
  twice (`scripts/tts.py` and `docs/app.js`) and `12-narration-mirror.py` is the only thing holding
  the two together.
- Change the PWA shell (`docs/app.js`, `index.html`, `styles.css`, `manifest.json`): bump `CACHE` in
  `docs/sw.js` in the same commit, or `shell-guard.yml` fails the push. Installed clients are served
  cache-first and would otherwise never update.
- Set it up as a user for the first time: top-level `README.md`.

## Scope

This documents the project as shipped. Everything below is live, not planned:

- v1 core — the must-knows, the four market numbers, tech and world news, the archive.
- v2 — market breadth (% of S&P 500 and Nasdaq-100 members above their 200-day average) with two
  alert tiers per index, and the daily audio edition.
- v3 — the policy section, the static policy calendar, and the 30-year mortgage rate.
- v4 — Owen's Alphabet Soup, the daily grounded lesson whose read-pointer lives in the phone's
  localStorage rather than in server state.
- v5 — the spoken rates readout, the Monday policy digest, cross-bucket audio dedupe, and
  self-healing lesson audio. Plus the "Health and science" and "Across the country" sections.
- v7 (2026-09-09) — the pulse becomes the WATCHLIST, plus an edge-triggered ntfy push the moment a
  ticker crosses into buy or trim range: any Yahoo ticker via `watchlist.txt`, a
  buy/trim/hold action computed once and used by both the card colour and the audio, audio that
  names only the actionable tickers, and configured-but-missing symbols named on the page.
- v6 (2026-09-09) — the leveraged ETF pulse: SOXL, SPXL and TQQQ with RSI-14 and their 1-month
  closing band, rendered under the must-knows and spoken in the same slot.

Areas that do not apply to this project are intentionally omitted: there is no database, no
authentication, and no internal API surface. The build writes static JSON that the PWA fetches.
