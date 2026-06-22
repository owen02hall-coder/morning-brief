# Brief: Fix daily auto-update (briefing frozen since 2026-06-16)

## Why
The morning briefing stopped updating — frozen at 2026-06-16 for 6 days — and the user got no
alert. Auto-update is actually *enabled and firing*; the problem is a silent no-op bug, not a
disabled cron. Every scheduled run completes in ~16s reporting "success" but produces no briefing.

## Context
- Workflow: `.github/workflows/briefing.yml` — two crons, `0 12 * * *` and `0 13 * * *` UTC
  (= 6am/7am America/Denver), plus `workflow_dispatch`. Public repo, free unlimited Actions.
- Hour-gate (root cause): `scripts/build_briefing.py:171-175`
  ```python
  if not (local or force):
      if _now().hour != config.RUN_HOUR_LOCAL:   # RUN_HOUR_LOCAL = 6
          print("no-op exit"); return 0
  ```
  `_now()` = `datetime.now(ZoneInfo("America/Denver"))` (`build_briefing.py:28`).
  `config.RUN_HOUR_LOCAL = 6`, `config.TIMEZONE = "America/Denver"` (`config.py:9-10`).
- The gate requires the job to *execute* at exactly 06:00 Denver. But GitHub delays scheduled
  workflows by hours under load. `gh run list` shows the 12:00/13:00 UTC crons actually executing
  at 17:00–21:30 UTC (= 11am–3:30pm Denver) every day. Hour is never 6 → every run no-ops.
- Because a no-op exits 0 ("success"), the `if: failure()` health ping never fired → 6 silent dead
  days. (Directly the failure mode the user's verify-by-mechanism rule warns about: a green label
  is not evidence of the real effect.)
- Idempotency anchor already exists: `state/state.json` → `{"last_run": "2026-06-16"}`, and
  `state.py` already loads/saves it. The published artifact `docs/briefing.json` carries a `"date"`.
- Everything stays free: GitHub Actions (public repo), FRED (keyless), Gemini free tier, ntfy. The
  fix changes logic only — no new services, no cost.

## Decisions
- **Replace the hour-equality gate with date-based idempotency.** Do real work only if
  `state.last_run != today` (Denver date) AND local hour >= 6. Whichever cron lands first that day
  does the work regardless of GitHub's delay; the second cron + any retry see `last_run == today`
  and no-op cleanly. Delay becomes irrelevant because nothing depends on the exact hour. — This is
  the core fix; the old `== 6` assumption that GitHub runs cron on time is false.
- **Keep a 6am-Denver floor** (don't build before hour 6). — Crons fire at 6/7am and delays only
  push later, so the floor never blocks a legitimate run; it just keeps it a true *morning*
  briefing and guards the rare past-midnight-delay edge case. Recommended over "no floor" for that
  small safety with zero downside.
- **Add a staleness watchdog that runs on EVERY invocation, including no-ops.** If the published
  `docs/briefing.json` date is older than ~26h, push an ntfy health alert. Must live *outside* the
  build/gate path so a silent no-op still pages — that is exactly the failure that bit us here.
  (User explicitly chose "Add staleness ping".)

## Rejected Alternatives
- **Schedule the cron earlier to absorb the delay** — doesn't fix anything; GitHub's delay is
  unbounded and unpredictable, so any fixed-hour equality gate stays fragile.
- **Remove the gate entirely / rely only on `concurrency`** — concurrency dedupes overlap but the
  two crons run hours apart, so both would do full work (double Gemini calls, double commits).
  Date idempotency is the correct dedupe key.
- **A separate monitoring service / external cron (e.g. cron-job.org, UptimeRobot)** — adds a
  dependency for something the run can self-check for free. The no-op run itself is the watchdog.

## Where Reasoning Clashed
None substantive. Only open choice was the 6am floor vs first-run-wins; user deferred to
recommendation and we kept the floor (negligible cost, small safety upside).

## One Thing to Do First
In `scripts/build_briefing.py:main`, replace the `_now().hour != RUN_HOUR_LOCAL` gate with:
build only if `state.last_run != today_denver` and `_now().hour >= RUN_HOUR_LOCAL`; otherwise no-op.

## Direction
Keep the existing free GitHub-Actions cron exactly as-is. Fix the silent freeze by deduping the
daily run on *date* (via `state.last_run`) with a 6am-local floor instead of an exact-hour gate, so
GitHub's multi-hour scheduling delays no longer cause every run to no-op. Add a self-contained
staleness check that runs on every invocation and ntfy-pings if the live briefing is >~26h old, so
a future silent freeze pages instead of masquerading as success.
