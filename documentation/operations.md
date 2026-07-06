---
title: Operations
source_files: [.github/workflows/, scripts/build_briefing.py, scripts/heartbeat.py, scripts/notify.py, scripts/briefing-assumptions/]
entry_points: [".github/workflows/briefing.yml", ".github/workflows/heartbeat.yml", ".github/workflows/shell-guard.yml", ".github/workflows/data-smoke.yml", "scripts/build_briefing.py:main", "scripts/heartbeat.py:main"]
last_verified: 2026-07-06
---

# Operations

How the briefing is scheduled, deployed, monitored, and recovered.

## Schedule

- Defined in `.github/workflows/briefing.yml` with two cron entries: `0 12 * * *` and `0 13 * * *`
  (UTC). GitHub cron is UTC only.
- 6am America/Denver is 12:00 UTC during daylight time and 13:00 UTC during standard time. Both
  crons fire. The script de-dupes by date (`state.last_run`): whichever cron lands first that day
  does real work, the rest see `last_run == today` and no-op. There is no hour comparison.
- The date stamp uses `zoneinfo("America/Denver")` via `_now()`, which needs the `tzdata` package
  (in requirements.txt).
- Scheduled runs can be delayed at peak load by GitHub — often by hours. The date-gate is built for
  exactly that: delay no longer prevents the day's build (an earlier hour-gate did, freezing the
  briefing for days). Do not reintroduce an exact-hour gate.

## Deployment (one-time)

1. Create a public GitHub repo and push this code. Public is required for free Pages and unlimited
   Actions minutes. The page is world-readable and contains only public news.
2. Repo Settings, Pages: Source "Deploy from a branch", branch `main`, folder `/docs`.
3. Repo Settings, Secrets and variables, Actions. Names must match what `briefing.yml` /
   `heartbeat.yml` reference (the workflows map the GitHub names into the env vars the code reads):
   - Secret `GEMINI_API_KEY` (read as `GEMINI_API_KEY`)
   - Secret `NTFY_SUB` (mapped to the `NTFY_TOPIC` env var the code reads)
   - Variable `PAGE_URL` set to the Pages URL (mapped to the `PAGES_URL` env var)
   - A name mismatch here is silent: a missing `NTFY_TOPIC` just skips every push, and a missing
     `PAGES_URL` falls back to a placeholder. If you rename a secret/var, update both workflows.
4. Install the ntfy app on the phone and subscribe to the same topic.
5. Actions tab, run the workflow once with "force" on. Then open the Pages URL on the phone and use
   Add to Home Screen.
6. The heartbeat workflow needs no extra setup; it reuses the same `NTFY_SUB` secret and `PAGE_URL`
   variable and starts its schedule once it is on the default branch.

## Runtime behavior

- Entry point: `python -m scripts.build_briefing`.
- Step order matters: the job fails fast if `NTFY_SUB` is empty (all alerting would be silent),
  installs `requirements.txt` with `-c constraints.txt` (CI-frozen transitive lock), runs the
  build (which also writes `headline.txt` and, on TTS success, `audio.mp3`), publishes the audio
  edition into `docs/` (manifest written only alongside a real mp3), commits `docs/` + `state/`
  and pushes (with a rebase-retry so a human push to main mid-run can't kill the day), and ONLY
  THEN sends the "ready" push via `python -m scripts.notify ready`. A failed publish can never
  follow a delivered "ready".
- The commit always changes `state.json` (last_run), so there is a daily renewing commit even on
  market holidays. This prevents the 60-day scheduled-workflow auto-disable.
- `permissions: contents: write` lets the token push. No personal access token is used, so the push
  does not retrigger the workflow (but it DOES trigger `shell-guard.yml`, which no-ops unless PWA
  shell files changed).
- `timeout-minutes: 10` bounds the job; the failure backstop fires on `failure() || cancelled()`
  so a timeout-kill still alerts.
- Actions are pinned by commit SHA; bump deliberately (look up the new tag's SHA, update all
  workflows, validate with a Data Smoke run).

## Monitoring

- Morning push: a "ready" ntfy is sent on a successful run, tapping through to the page.
- Health ping: if any section is unavailable, a low-priority "degraded" ntfy lists the sections. If
  the run crashes, the Python layer sends a high-priority "FAILED" ntfy. A workflow `if: failure()`
  step sends a backstop ntfy in case the crash happens before Python can.
- Market blackout escalation: the build tracks `markets_last_ok` in `state.json`. A single day with
  all four numbers missing is a low-priority "degraded" ping, but once they've been unavailable for
  `MARKETS_STALE_DAYS` (2) days running — a dead source, not a blip — it escalates to a high-priority
  ntfy. This exists because the prior source (FRED) died silently and degraded for days unnoticed.
  When no usable `markets_last_ok` baseline exists (fresh deployment / reset state), the build
  anchors `markets_first_bad` instead, so a source that has never been healthy escalates on the
  same schedule rather than degrading silently forever.
- Heartbeat: an independent workflow (`.github/workflows/heartbeat.yml`, daily at 03:00 UTC) fetches
  the LIVE Pages `briefing.json` and, if it is older than `HEARTBEAT_STALE_HOURS` (30h) or
  unreachable, sends a high-priority ntfy AND fails the job (so its own `if: failure()` curl fires
  as a second alarm leg — independent of the Python process, though every alarm leg still terminates
  at the same ntfy topic, an accepted v1 trade-off). Because it runs on its own schedule and checks
  the real page, it catches both a build that silently no-ops and a build cron that GitHub dropped
  entirely.
- Breadth alerts (per index, S&P 500 and Nasdaq-100): a one-shot normal-priority warning when
  breadth falls below 40% (re-armed only after recovering to 42), and a high-priority daily nag
  below 30% with a day counter (clears at 33, EXTREME below 20). Both suppressed on stale data.
- Shell guard: `shell-guard.yml` fails any push that changes `docs/` shell files without bumping
  the sw.js CACHE constant, and ntfy-pages on trip — installed PWAs would otherwise silently
  never update (this class shipped broken once).
- Data smoke: `data-smoke.yml` (manual dispatch) prints the whole data spine from a runner and
  fails if breadth doesn't compute — run it after touching any data source.
- Transparency: `briefing.json` carries a `data_availability` map showing each section's status.

## Failure modes and recovery

- A dead RSS feed: skipped per-feed. If all world feeds are down, the world section reads
  "information not available" but the briefing still ships.
- Yahoo slow or down: that number degrades to None and shows as unavailable. The client retries and
  tries the query1/query2 hosts, with a short fail-fast timeout so it can't stall the build.
- Gemini down: the model fallback runs, then the no-AI fallback (raw numbers and headlines). The day
  is never skipped.
- A skipped or failed day: the PWA shows an age-based "could not refresh, last updated X" notice
  rather than presenting old data as current.
- A wrong tap-through link: if `PAGES_URL` is still the placeholder, `notify.morning_ready` prints a
  loud warning.
- TradingView scan fails or matches too few constituents: that index's breadth serves the cached
  last-good value (dated, marked stale) for up to 2 trading days, then shows unavailable. The
  briefing still ships; alerts are suppressed on stale values.
- Gemini TTS fails: no manifest is written, the page's Listen button falls back to the on-device
  voice, and the degraded ping includes "audio". The briefing still ships.
- GitHub Pages deploy fails with "Deployment failed, try again later": transient — re-run it
  (`gh run rerun <id>`).

## Regression tests

- Pre-flight and regression assumption tests live in `scripts/briefing-assumptions/`.
- Run them: `BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh`.
- `04-external-boundary-smoke.py` needs no key and checks RSS and Wikipedia liveness. Tests 01 and
  02 need a Twelve Data key and target v2 breadth. Test 03 needs a Gemini key.

## Cost

- Zero per month. Yahoo Finance, RSS, ntfy, GitHub Pages, and GitHub Actions (public repo) are free. Gemini
  runs on the free tier. The Gemini project must keep billing disabled to stay free.

## Local development

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=... NTFY_TOPIC=...      # PowerShell: $env:NAME="..."
python -m scripts.build_briefing --spine              # market numbers + news counts, no key needed
python -m scripts.build_briefing --local --no-notify  # write docs/briefing.json, no push
```
