"""Orchestrator for the morning briefing (v1 core).

Run modes:
  python -m scripts.build_briefing            # CI: builds once per day (first cron that lands; rest no-op)
  python -m scripts.build_briefing --force    # bypass the once-per-day gate and build now (CI manual)
  python -m scripts.build_briefing --local    # bypass the once-per-day gate and build now (local dev)
  python -m scripts.build_briefing --spine     # quick check: print market numbers + news counts
  python -m scripts.build_briefing --no-notify # skip ntfy pushes

Flow: date-gate -> load state -> market (Yahoo, all four numbers) -> news (RSS) -> Gemini summary
(with a no-AI fallback) -> write briefing.json + archive + state + headline handoff -> health
pings. The daily "ready" push is NOT sent here: the build writes headline.txt and the workflow
sends the push (scripts.notify CLI) only after the commit/push leg succeeds, so a failed publish
can never follow a delivered "ready". The whole run is wrapped so an unhandled failure sends a
high-priority health ping and exits non-zero.
"""
import glob
import json
import os
import sys
import traceback
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config, state, notify
from .data import market as market_mod
from .data import news as news_mod
from . import summarize as summarize_mod


def _now():
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _days_since(iso_date, today_iso):
    """Whole days between two YYYY-MM-DD strings, or None if the first is missing/unparseable."""
    try:
        return (date.fromisoformat(today_iso) - date.fromisoformat(iso_date)).days
    except (TypeError, ValueError):
        return None


def _recap_context():
    """Up to the last 7 archived briefings, condensed, for the Sunday weekly recap."""
    files = [f for f in sorted(glob.glob(os.path.join(config.ARCHIVE_DIR, "*.json")))
             if os.path.basename(f) != "index.json"][-7:]
    lines = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                b = json.load(fh)
            lines.append(f"{b.get('date')}: " + " | ".join(b.get("tldr", [])[:2]))
        except Exception:
            continue
    return "\n".join(lines)


def _fallback_items(news, bucket, limit):
    return [{"summary": a["title"], "source": a["source"], "url": a["url"]}
            for a in news.get(bucket, [])[:limit]]


def _assemble(now, today, market, news, narrative, ai_ok):
    briefing_date = today
    avail = {**market["availability"], **{f"news_{k}": v for k, v in news["available"].items()},
             "summary": "ok" if ai_ok else "unavailable"}

    def num(n, why):
        if not n:
            return None
        return {"value": n["value"], "change": n["change"], "asof": n["asof"], "why": why}

    if ai_ok:
        tldr = narrative["tldr"]
        market_block = {"sp500": market["sp500"], "ndx": market["ndx"], "why": narrative["market_why"]}
        yield_block = num(market["ten_year"], narrative["yield_why"])
        vix_block = num(market["vix"], narrative["vix_why"])
        tech, world = narrative["tech"], narrative["world"]
        recap = narrative.get("weekly_recap")
    else:
        tldr = ["AI summary unavailable today — showing raw market numbers and headlines."]
        market_block = {"sp500": market["sp500"], "ndx": market["ndx"], "why": ""}
        yield_block = num(market["ten_year"], "")
        vix_block = num(market["vix"], "")
        tech = _fallback_items(news, "tech", config.MAX_TECH_ITEMS)
        world = _fallback_items(news, "world", config.MAX_WORLD_ITEMS)
        recap = None

    return {
        "generated_at": now.isoformat(),
        "date": briefing_date,
        "tldr": tldr,
        "market": market_block,
        "yield_10y": yield_block,
        "vix": vix_block,
        "tech": tech,
        "world": world,
        "weekly_recap": recap,
        "data_availability": avail,
    }


def _write(briefing):
    os.makedirs(config.DOCS_DIR, exist_ok=True)
    os.makedirs(config.ARCHIVE_DIR, exist_ok=True)
    with open(config.BRIEFING_PATH, "w", encoding="utf-8") as f:
        json.dump(briefing, f, indent=2)
    with open(os.path.join(config.ARCHIVE_DIR, f"{briefing['date']}.json"), "w", encoding="utf-8") as f:
        json.dump(briefing, f, indent=2)
    _write_archive_index()


def _write_archive_index():
    """Maintain docs/archive/index.json — GitHub Pages can't list a directory, so the PWA
    reads this manifest to populate the searchable archive."""
    entries = []
    for f in sorted(glob.glob(os.path.join(config.ARCHIVE_DIR, "*.json")), reverse=True):
        name = os.path.basename(f)
        if name == "index.json":
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                b = json.load(fh)
            entries.append({"date": b.get("date"), "tldr": b.get("tldr", [])[:1]})
        except Exception:
            continue
    with open(os.path.join(config.ARCHIVE_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def run(do_notify=True, today=None):
    now = _now()
    # `today` is the gate's date, passed from main() so the build decision and the saved state stamp
    # use one identical date (no midnight-cross skew between two _now() reads). Falls back for --force/
    # --local/direct callers that don't gate.
    today = today or now.date().isoformat()
    st = state.load()
    prev_markets_ok = st.get("markets_last_ok")   # last date all four market numbers were available

    market = market_mod.get_market()
    news = news_mod.get_news()

    # Derive the weekday from the gate date so the build decision, the saved briefing date, and the
    # Sunday-recap choice all agree even if midnight crosses between _now() reads.
    is_sunday = date.fromisoformat(today).weekday() == 6
    narrative, ai_ok = summarize_mod.summarize(
        market, news, is_sunday, recap_context=_recap_context() if is_sunday else "")

    briefing = _assemble(now, today, market, news, narrative, ai_ok)
    _write(briefing)

    # Track the last day markets were fully healthy, so a SUSTAINED blackout (a dead data source, the
    # way FRED silently died) can be escalated loudly below instead of degrading unnoticed for days.
    markets_ok = all(briefing["data_availability"].get(k)
                     for k in ("sp500", "ndx", "vix", "ten_year"))
    if markets_ok:
        st = {k: v for k, v in {**st, "markets_last_ok": today}.items()
              if k != "markets_first_bad"}
    elif (_days_since(prev_markets_ok, today) is None
          and _days_since(st.get("markets_first_bad"), today) is None):
        # No USABLE healthy-day baseline (fresh deployment, reset state, or an unparseable
        # markets_last_ok value): anchor the blackout's first day so a source that is dead from
        # day one still escalates below. The seed condition must mirror the alert's
        # `stale is None` branch exactly — if they diverge, that branch reads an anchor that was
        # never written and the escalation goes permanently silent.
        st = {**st, "markets_first_bad": today}
    state.save(st, today)

    # Ready-push handoff: the "your briefing is ready" push must fire AFTER the commit/push/Pages
    # deploy — not here, mid-build, where a later publish failure would make it a lie. Write the
    # headline to a handoff file; the workflow's post-publish step sends it via
    # `python -m scripts.notify ready`. On a good day, tease the top must-know; on a no-AI fallback
    # day the first tldr line is an internal notice, so hand off a clean generic message instead.
    headline = (briefing["tldr"][0] if ai_ok and briefing["tldr"]
                else "Your morning briefing is ready.")
    with open(config.HEADLINE_PATH, "w", encoding="utf-8") as f:
        f.write(headline + "\n")

    # health: report any degraded section (low priority); the run still succeeded
    degraded = [k for k, v in briefing["data_availability"].items()
                if v is False or v == "unavailable"]
    if do_notify:
        if degraded:
            notify.health("degraded sections: " + ", ".join(degraded), ok=True)
        # Loud escalation: markets blank for >= MARKETS_STALE_DAYS in a row means the source is likely
        # down, not a one-day blip — page high-priority (a single bad day stays low-priority above).
        if not markets_ok:
            stale = _days_since(prev_markets_ok, today)
            if stale is not None and stale >= config.MARKETS_STALE_DAYS:
                notify.health(f"market data unavailable {stale} days running (last ok {prev_markets_ok}) "
                              "— the market source may be down", ok=False)
            elif stale is None:
                # No healthy day on record: measure the blackout from its first recorded bad day
                # (seeded above) so a never-healthy source pages instead of degrading silently forever.
                first_bad = st.get("markets_first_bad")
                bad_days = _days_since(first_bad, today)
                if bad_days is not None and bad_days + 1 >= config.MARKETS_STALE_DAYS:
                    notify.health(f"market data unavailable since {first_bad} ({bad_days + 1} days) with "
                                  "no healthy day on record — the market source may be down or misconfigured",
                                  ok=False)

    print(f"briefing written for {briefing['date']} (ai={'ok' if ai_ok else 'fallback'}, "
          f"degraded={degraded or 'none'})")
    return briefing


def spine():
    """Quick read-out of the data spine (no files written)."""
    m = market_mod.get_market()
    n = news_mod.get_news()
    print("S&P 500:", m["sp500"]); print("Nasdaq:", m["ndx"])
    print("VIX:", m["vix"]); print("10-yr:", m["ten_year"])
    print("news candidates: world=%d business=%d tech=%d" %
          (len(n["world"]), len(n["business"]), len(n["tech"])))


def main(argv):
    if "--spine" in argv:
        spine()
        return 0

    local = "--local" in argv
    force = "--force" in argv
    do_notify = "--no-notify" not in argv and not local

    today = _now().date().isoformat()
    if not (local or force):
        # Once-per-day gate: whichever cron lands first that day builds; the rest (and retries) no-op.
        # De-duping by DATE, not by hour, makes GitHub's multi-hour schedule delays irrelevant.
        if state.load().get("last_run") == today:
            print("no-op exit (already built today)")
            return 0

    try:
        run(do_notify=do_notify, today=today)
        return 0
    except Exception as e:
        traceback.print_exc()
        if do_notify:
            notify.health(f"briefing run crashed: {e}", ok=False)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
