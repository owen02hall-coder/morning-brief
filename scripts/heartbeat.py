"""Independent liveness check: is the LIVE published briefing fresh?

Runs on its own GitHub Actions cron (`.github/workflows/heartbeat.yml`), separate from the build, so
it catches BOTH a build that silently no-ops AND a scheduled build that GitHub dropped entirely. It
fetches the real Pages artifact — what the phone actually loads — not the committed file. On a stale
or unreachable page it pings ntfy AND exits non-zero, so the workflow's `if: failure()` curl backstop
fires as a second alarm path. That backstop is independent of THIS PYTHON PROCESS (it still alerts if
this script crashes before pushing), but it is NOT ntfy-independent — every alarm leg terminates at
the same ntfy.sh topic, so an ntfy outage silences all of them. Accepted v1 trade-off.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, notify


def _now():
    return datetime.now(ZoneInfo(config.TIMEZONE))


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
