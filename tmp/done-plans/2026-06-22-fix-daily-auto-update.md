# Plan: Fix daily auto-update (briefing frozen since 2026-06-16)

> Source brief: `./tmp/briefs/2026-06-22-fix-daily-auto-update.md` (decisions there are settled).
> Revised after a 2-reviewer + criticer + meta-pass review — see "Design decisions from review" below.

## Problem (one paragraph)

The daily GitHub Actions cron **is** firing and reporting "success," but the briefing has been frozen
at 2026-06-16 for 6 days. Root cause: `scripts/build_briefing.py:173` gates real work on
`_now().hour != config.RUN_HOUR_LOCAL` (exactly 06:00 America/Denver). GitHub delays scheduled
workflows by hours under load — `gh run list` shows the 12:00/13:00 UTC crons actually executing at
17:00–21:30 UTC (11am–3:30pm Denver) every day — so the hour is never `6` and **every run no-ops in
~16s.** A no-op exits 0, so the workflow's `if: failure()` health ping never fires → 6 silent dead
days. `documentation/operations.md:21` literally warns "Scheduled runs can be delayed… Do not assume
on-time delivery," yet the gate assumed exactly that.

## Fix

**1. Gate on date, not hour (the actual fix).** Replace the exact-hour gate with pure once-per-day
idempotency: build only if `state.last_run != today` (America/Denver date). The first cron to land
each day builds regardless of delay; the second cron + any retry see `last_run == today` and no-op
cleanly. No hour arithmetic survives — the fix's whole thesis ("stop depending on when GitHub runs
the job") is honoured completely.

**2. External heartbeat workflow (the monitor).** A separate, independent daily workflow curls the
**live GitHub Pages `briefing.json`**, parses its `generated_at`, and if it's older than
`HEARTBEAT_STALE_HOURS` (or unreachable/unparseable) it (a) sends a high-priority ntfy ping **and**
(b) exits non-zero so the workflow's own `if: failure()` curl backstop also fires. This checks the
real artifact the phone loads (not a committed-file proxy), runs on its own schedule (so it catches a
*dropped* main run, not just a wrong no-op), and has an ntfy-independent alarm path.

No new accounts, secrets, or paid services. Still 100% free (GitHub Actions public repo, FRED keyless,
Gemini free tier, ntfy). Reuses the existing `NTFY_TOPIC` secret and `PAGES_URL` variable.

### Design decisions from review (why this differs from the first draft)

- **Dropped the 6am floor → strict first-run-wins.** The criticer noted a floor reintroduces the exact
  hour-dependence the fix rejects (a run delayed from the prior night landing pre-6am would no-op and
  defer to a cron that might be dropped). With first-run-wins the gate is purely `last_run != today` —
  zero hour logic. The briefing is timestamped by `generated_at` regardless of when it builds, so an
  occasional early build is harmless.
- **Replaced the in-script no-op watchdog with the external heartbeat.** Both reviewers showed the
  in-script watchdog was fire-and-forget (ntfy down → run still exits 0 → `if: failure()` never fires)
  and that it read the *committed* `docs/briefing.json`, not the *published* page. The heartbeat fixes
  both (exit 1 backstop; live-URL fetch) and additionally covers the dropped-run gap. One staleness
  mechanism, one threshold — avoids the "two ways to do the same thing" smell of keeping both.

## Files Being Changed

```
scripts/
  build_briefing.py        ← MODIFIED  (replace hour-gate with pure date-gate; update module docstring)
  config.py                ← MODIFIED  (RUN_HOUR_LOCAL removed; add HEARTBEAT_STALE_HOURS = 30)
  heartbeat.py             ← NEW       (fetch live Pages briefing.json; ntfy + exit 1 if stale/unreachable)
.github/workflows/
  briefing.yml             ← MODIFIED  (comment only: describe the date-gate, not the old hour-gate)
  heartbeat.yml            ← NEW       (independent daily cron; runs scripts.heartbeat; own failure backstop)
documentation/
  architecture.md          ← MODIFIED  (wording: hour-gate → once-per-day date-gate; add heartbeat to modules/flow)
  operations.md            ← MODIFIED  (wording: hour-gate → date-gate; document the heartbeat monitor)
```

No code is deleted beyond the rewritten gate and the now-unused `RUN_HOUR_LOCAL`. No tests (per plan
rules). `scripts/state.py` is unchanged — `load()` already returns `last_run`, `save()` already stamps
today. `scripts/notify.py` is unchanged — `heartbeat.py` reuses `notify.health(ok=False)`.

## Architecture Overview

**Build path** — `main()` in `build_briefing.py` (CI default, `not local and not force`):

```
today = _now().date().isoformat()          # America/Denver
st    = state.load()                        # {"last_run": "YYYY-MM-DD" | None}
if st.get("last_run") == today:             # already built today → second cron / retry
    print("no-op exit (already built today)")
    return 0
run(do_notify=do_notify)                    # build + write briefing.json + archive + state + ping ready
return 0
```

That is the entire gate. `--force` (manual dispatch) and `--local` (dev) still bypass it and always
build. Cold start: committed `last_run` is `"2026-06-16"` → `!= today` → builds on the first scheduled
run after merge. `run()` is unchanged; it re-reads state once and calls `state.save(st, today)` — to
remove the double `_now()`/`state.load()` and any midnight-cross skew, pass `today` down (see Task 2b).

**Monitor path** — `scripts/heartbeat.py`, run by `heartbeat.yml` on its own daily cron, fully
independent of the build:

```
url   = PAGES_URL.rstrip('/') + '/briefing.json?cb=' + os.environ.get('GITHUB_RUN_ID','0')   # CDN cache-bust
fetch url (no-cache header, timeout)
  unreachable / non-200 / unparseable      -> notify.health("heartbeat: live briefing unreachable/...", ok=False); exit 1
  age = _now() - fromisoformat(generated_at)
  age > HEARTBEAT_STALE_HOURS               -> notify.health(f"heartbeat: live briefing {age}h stale", ok=False); exit 1
  else                                      -> print ok; exit 0
```

The two alarm legs are deliberately redundant and independent: the in-process `notify.health` ntfy
push, and — because the process `exit 1`s — the workflow's `if: failure()` curl step (an ntfy POST
that does not depend on the Python push having worked). If ntfy is up, you may get both; that is
acceptable for a real outage.

## Key Pseudocode

### `scripts/config.py`

Remove `RUN_HOUR_LOCAL` (line 10) — nothing references it after this change. Add, near `STALE_HOURS`
(line 64):

```python
# --- Monitoring -------------------------------------------------------------
STALE_HOURS = 28            # client: the PWA shows "couldn't refresh" past this age (unchanged)
HEARTBEAT_STALE_HOURS = 30  # server: heartbeat.yml pages if the LIVE page is older than this.
                            # > 24h + GitHub's worst observed schedule jitter (~9h on build AND on the
                            # heartbeat itself) so a healthy-but-jittery day never false-alarms; a real
                            # multi-day freeze (the bug this fixes) trips it well within a day of going stale.
```

`TIMEZONE` stays (used by `_now()`). The single-user nature means operator == reader, so the 28h-client
vs 30h-heartbeat ordering is immaterial.

### `scripts/heartbeat.py` (NEW)

```python
"""Independent liveness check: is the LIVE published briefing fresh?

Runs on its own GitHub Actions cron (heartbeat.yml), separate from the build, so it catches BOTH a
build that silently no-ops AND a scheduled build that GitHub dropped entirely. Fetches the real Pages
artifact (what the phone loads), not the committed file. On stale/unreachable it pings ntfy AND exits
non-zero so the workflow's failure backstop is a second, ntfy-independent alarm.
"""
import os, sys, json, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo
from . import config, notify

def _now():
    return datetime.now(ZoneInfo(config.TIMEZONE))

def main():
    url = config.PAGES_URL.rstrip("/") + "/briefing.json?cb=" + os.environ.get("GITHUB_RUN_ID", "0")
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = json.load(r)
        gen = datetime.fromisoformat(b["generated_at"])              # tz-aware (Denver offset)
        age = (_now() - gen).total_seconds() / 3600.0
    except Exception as e:
        notify.health(f"heartbeat: live briefing unreachable/unparseable ({e})", ok=False)
        return 1
    if age > config.HEARTBEAT_STALE_HOURS:
        notify.health(f"heartbeat: live briefing is {age:.0f}h stale — daily build may have stopped", ok=False)
        return 1
    print(f"heartbeat ok: live briefing {age:.1f}h old")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### `scripts/build_briefing.py` — replace the gate in `main()` (current lines 171-175)

```python
    if not (local or force):
        today = _now().date().isoformat()
        if state.load().get("last_run") == today:
            print("no-op exit (already built today)")
            return 0
    ...
    run(do_notify=do_notify)   # existing try/except block unchanged
```

### `.github/workflows/heartbeat.yml` (NEW)

```yaml
name: Briefing Heartbeat
on:
  schedule:
    - cron: "0 3 * * *"        # 03:00 UTC ~ 8-9pm Denver — well after the morning build window
  workflow_dispatch:
permissions:
  contents: read
jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - name: Check live briefing freshness
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
          PAGES_URL: ${{ vars.PAGES_URL }}
        run: python -m scripts.heartbeat
      - name: Failure backstop (ntfy-independent of the python push)
        if: failure()
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: |
          if [ -n "${NTFY_TOPIC}" ]; then
            curl -s -H "Title: Heartbeat FAILED" -H "Priority: high" \
              -d "The briefing heartbeat job failed or found a stale page. Check Actions." \
              "https://ntfy.sh/${NTFY_TOPIC}" || true
          fi
```

## Tasks (in order)

1. **`scripts/config.py`** — Delete the `RUN_HOUR_LOCAL = 6` line (line 10). Add the `HEARTBEAT_STALE_HOURS`
   block next to `STALE_HOURS` (line 64) per pseudocode. Leave `TIMEZONE` and `STALE_HOURS` as-is.

2. **`scripts/build_briefing.py`** —
   a. Replace the gate block (lines 171-175) with the pure date-gate above (drops the `_now().hour`
      comparison and the `RUN_HOUR_LOCAL` reference entirely).
   b. Thread the date through to avoid a double `_now()`/midnight skew: compute `today` once in `main()`
      and pass it into `run(do_notify, today)`; inside `run()` use the passed `today` for both the
      `now`-derived fields it already builds and `state.save(st, today)`. (Small signature change;
      `run()` currently computes `now = _now()` at line 121 and `state.save(st, now.date().isoformat())`
      at line 133 — keep `now` for `generated_at`/weekday but use the passed `today` for the state stamp
      so the gate decision and the saved date are guaranteed identical.)
   c. Update the module docstring: line 4 ("only does work if it's ~6am America/Denver") → "only does
      work once per day (first cron that lands; the rest no-op)"; line 5 ("regardless of the hour") and
      line 6 ("skip the hour-gate") → "bypass the once-per-day gate"; line 10 ("Flow: hour-gate -> …") →
      "Flow: once-per-day date-gate -> …".

3. **`scripts/heartbeat.py`** — Create per pseudocode. Self-contained; imports only `config` + `notify`.

4. **`.github/workflows/heartbeat.yml`** — Create per pseudocode. Note `permissions: contents: read`
   (no write needed — it never commits).

5. **`.github/workflows/briefing.yml`** — Comment-only edit at lines 5-6: replace "the script's
   hour-gate makes exactly one do real work" with "the script de-dupes by date (`state.last_run`), so
   whichever delayed cron lands first that day builds and the rest no-op." Keep both crons (they are the
   redundancy that makes first-to-land-wins work) and the `force` input.

6. **`documentation/architecture.md`** — Replace hour-gate wording at lines 25, 44, 93, 95 with the
   once-per-day date-gate. Add a one-line mention of `scripts/heartbeat.py` + `heartbeat.yml` in the
   modules/flow sections.

7. **`documentation/operations.md`** — Replace the hour-gate description at lines 16-19 (including line
   19's "the hour-gate uses zoneinfo" → "`_now()` uses zoneinfo") with the date-gate. Keep line 21's
   delay caveat (now correctly handled). Add a "Monitoring" bullet: the independent `heartbeat.yml`
   curls the live page daily and pages (ntfy + job failure) if it is >`HEARTBEAT_STALE_HOURS` stale or
   unreachable.

## Validation Gates (AI-executable, offline, no keys)

```bash
cd "C:/Users/User/Desktop/AI CODE/News"

# 1. Everything imports; RUN_HOUR_LOCAL is truly gone (no dangling refs)
python -c "import scripts.build_briefing, scripts.heartbeat, scripts.config"
python -c "import scripts.config as c; assert not hasattr(c,'RUN_HOUR_LOCAL'), 'RUN_HOUR_LOCAL still referenced'"
grep -rn "RUN_HOUR_LOCAL" scripts/ && echo "FAIL: lingering RUN_HOUR_LOCAL" || echo "OK: no RUN_HOUR_LOCAL"

# 2. Date-gate no-ops when last_run == today (NTFY unset → pushes safely skipped), exit 0
python - <<'PY'
import scripts.build_briefing as b, scripts.state as state
state.load = lambda: {"last_run": b._now().date().isoformat()}   # pretend already built today
assert b.main([]) == 0
PY

# 3. Heartbeat staleness branch fires: monkeypatch a >threshold age, assert notify.health(ok=False) called + exit 1
python - <<'PY'
import scripts.heartbeat as h, scripts.notify as notify, scripts.config as c
calls = []
notify.health = lambda msg, ok=True: calls.append(ok)
# force the fetch to yield a very old generated_at by patching urlopen
import io, json
class _Resp:
    def __enter__(self): return io.BytesIO(json.dumps({"generated_at":"2000-01-01T00:00:00-07:00"}).encode())
    def __exit__(self,*a): return False
import urllib.request; urllib.request.urlopen = lambda *a, **k: _Resp()
rc = h.main()
assert rc == 1 and calls == [False], (rc, calls)
print("heartbeat stale-branch OK")
PY

# 4. Spine still works (no key needed) — proves the data path is untouched
python -m scripts.build_briefing --spine
```

## Gotchas

- **`generated_at` is tz-aware** (`now.isoformat()` carries the Denver offset). `_now()` is tz-aware too,
  so the subtraction is valid in both files. Never compare against a naive `datetime.now()`.
- **First heartbeat after merge will legitimately page once** if the live page is still the 2026-06-16
  briefing (~6 days stale) when it first runs — that is correct (the page *is* stale until the first
  post-merge build publishes). Expected, not a regression.
- **CDN caching on Pages** — the `?cb=$GITHUB_RUN_ID` query + `Cache-Control: no-cache` header dodge a
  stale CDN copy so the heartbeat reads the truly-current artifact.
- **Heartbeat threshold must absorb compounded jitter.** Both the build and the heartbeat can be delayed
  hours; 30h sits above 24h + worst observed jitter so a healthy day never trips. It is a multi-day-freeze
  backstop, not a punctuality check — do not tighten it toward 24h.
- **Dropped-run residual:** if GitHub drops *both* build crons on a given day, that day self-heals next
  build with no alert; only a *persistent* freeze accumulates past 30h and pages. That is the intended
  bound (the heartbeat is the safety net for sustained freezes, which is the failure that occurred).
- **`tzdata`** is already in `requirements.txt` — no new dependency. `heartbeat.py` uses only stdlib +
  existing modules.
- **Two crons stay** in `briefing.yml`; date-de-dupe makes a double-firing safe (second no-ops).

## Deprecated / Removed Code

- `config.RUN_HOUR_LOCAL` — deleted; no longer referenced once the date-gate lands (gate #1 of the
  validation suite fails if any reference survives).

## Confidence

**9/10** for one-pass success. The behavioural fix is a few lines in one function; monitoring is a small
self-contained module + a standard workflow mirroring the existing `briefing.yml` shape. Root cause is
confirmed against live `gh run list` data, and all four validation gates run offline.

## Criticer Notes

1. **Watchdog only fires once/day and only if a run lands.** GitHub can *drop* a delayed cron entirely,
   not just postpone it. (Addressed in this revision: the heartbeat runs on its own independent cron and
   checks the live page, so it catches a dropped build, not only a wrong no-op. The residual — both the
   build crons AND the heartbeat cron all dropped on the same day — self-heals next run and is bounded
   by `HEARTBEAT_STALE_HOURS`.)
2. **The 6am floor reintroduces a smaller version of the same fragility.** (Addressed: floor dropped;
   the gate is now purely `last_run != today` with zero hour-dependence.)
3. **The lowest-effort coverage for the dropped-run gap is external to the run.** (Adopted: the monitor
   is now an external heartbeat workflow hitting the live Pages URL, not an in-script self-check.)
