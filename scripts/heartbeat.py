"""Independent liveness check: is the LIVE published briefing fresh?

Runs on its own GitHub Actions cron (`.github/workflows/heartbeat.yml`), separate from the build, so
it catches BOTH a build that silently no-ops AND a scheduled build that GitHub dropped entirely. It
fetches the real Pages artifact — what the phone actually loads — not the committed file. On a stale
or unreachable page it pings ntfy AND exits non-zero, so the workflow's `if: failure()` curl backstop
fires as a second alarm path. That backstop is independent of THIS PYTHON PROCESS (it still alerts if
this script crashes before pushing), but it is NOT ntfy-independent — every alarm leg terminates at
the same ntfy.sh topic, so an ntfy outage silences all of them. Accepted v1 trade-off.

IT ALSO WATCHES THE WATCHDOG. `data-smoke.yml` is the weekly drift detector, and a red smoke run
pages — but a smoke run that NEVER HAPPENS is completely silent, which is the same shape as the
bug that started all of this: Nasdaq-100 breadth stayed dead for 22 days because the guard existed
and its trigger did not. GitHub drops and delays scheduled workflows, so "the cron is configured" is
a hypothesis about behaviour, not evidence of it. This job already runs daily and already owns the
ntfy topic, so it is the cheapest honest place to assert that a SCHEDULED smoke ran recently.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, notify


def _now():
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _smoke_schedule_age_days():
    """Days since the last SCHEDULED Data Smoke run completed, or None if it cannot be determined.

    None is "unknown", NOT "healthy" — but it is deliberately not an alert either. This runs every
    day against a 9-day threshold, so one unreachable API call costs nothing: eight more attempts
    land before the answer could matter. Alerting on a single transient blip would add noise to the
    one channel that has to stay worth reading. A PERSISTENT failure is the real risk, and it shows
    up as the staleness alert firing anyway once the clock runs out.

    `event=schedule` is load-bearing. A manual dispatch proves the tests pass; only a scheduled run
    proves the TRIGGER still fires, and the trigger is what goes missing.
    """
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        print("heartbeat: no GITHUB_REPOSITORY/GITHUB_TOKEN — skipping the smoke-schedule check")
        return None
    url = (f"https://api.github.com/repos/{repo}/actions/workflows/data-smoke.yml/runs"
           f"?event=schedule&status=completed&per_page=1")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": config.USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            runs = json.load(r).get("workflow_runs") or []
    except Exception as e:                       # noqa: BLE001 - see the docstring: unknown != alert
        print(f"heartbeat: could not read Data Smoke history ({type(e).__name__}: {e}) — "
              "skipping the smoke-schedule check this run")
        return None
    if not runs:
        print("heartbeat: no COMPLETED SCHEDULED Data Smoke run has ever been recorded")
        return None
    finished = runs[0].get("updated_at") or runs[0].get("created_at")
    try:
        when = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        print(f"heartbeat: unparseable Data Smoke timestamp {finished!r}")
        return None
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400.0


def check_smoke_schedule():
    """Alert when the weekly drift detector has stopped being triggered. Returns True if healthy.

    Sent via notify.monitoring(), NOT notify.health(): "Briefing degraded" would point the reader at
    an edition that is perfectly fine. And no non-zero exit, on purpose — that would fire the
    "Heartbeat FAILED" high-priority backstop and claim the daily check died. What has failed is the
    ability to NOTICE things breaking, which is worth a message today and not worth a 3am page.
    """
    age = _smoke_schedule_age_days()
    if age is None:
        return True                              # unknown: say nothing, try again tomorrow
    if age > config.SMOKE_STALE_DAYS:
        notify.monitoring(
            f"no SCHEDULED Data Smoke in {age:.0f} days (weekly cron) — the drift detector has "
            f"stopped being triggered. Every data leg is now unwatched between builds; this is how "
            f"Nasdaq-100 breadth stayed dead for 22 days. Check the workflow's schedule.")
        print(f"heartbeat: SMOKE SCHEDULE STALE — {age:.1f} days since the last scheduled run")
        return False
    print(f"heartbeat: smoke schedule ok — last scheduled run {age:.1f} days ago")
    return True


def main():
    # Cache-bust the Pages CDN so we read the truly-current artifact, not a stale edge copy.
    url = config.PAGES_URL.rstrip("/") + "/briefing.json?cb=" + os.environ.get("GITHUB_RUN_ID", "0")
    req = urllib.request.Request(
        url, headers={"User-Agent": config.USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            briefing = json.load(r)
        gen = datetime.fromisoformat(briefing["generated_at"])   # tz-aware (Denver offset)
        age = (_now() - gen).total_seconds() / 3600.0
    except Exception as e:
        notify.health(f"heartbeat: live briefing unreachable/unparseable ({e})", ok=False)
        return 1

    if age > config.HEARTBEAT_STALE_HOURS:
        notify.health(
            f"heartbeat: live briefing is {age:.0f}h stale — daily build may have stopped", ok=False)
        return 1

    print(f"heartbeat ok: live briefing {age:.1f}h old")
    # Runs AFTER the briefing verdict and cannot change it: a stale smoke schedule is a monitoring
    # problem, not a reader-facing one, and must not turn a healthy morning into a red heartbeat.
    check_smoke_schedule()
    return 0


if __name__ == "__main__":
    sys.exit(main())
