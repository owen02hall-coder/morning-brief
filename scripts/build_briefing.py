"""Orchestrator for the morning briefing (v1 core).

Run modes:
  python -m scripts.build_briefing            # CI: builds once per day (first cron that lands; rest no-op)
  python -m scripts.build_briefing --force    # bypass the once-per-day gate and build now (CI manual)
  python -m scripts.build_briefing --local    # bypass the once-per-day gate and build now (local dev)
  python -m scripts.build_briefing --spine     # quick check: print market numbers + news counts
  python -m scripts.build_briefing --no-notify # skip ntfy pushes

Flow: date-gate -> load state -> market (Yahoo, all four numbers) + mortgage (PMMS) -> news (RSS)
-> breadth -> policy (re-emit-or-fetch, then its own Gemini call) -> Gemini summary
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
from . import tts as tts_mod
from .data import market as market_mod
from .data import news as news_mod
from .data import mortgage as mortgage_mod
from .data import policy as policy_mod
from .breadth import percent_above_ma as breadth_mod
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


def _get_breadth(st, today):
    """Per-index breadth with per-index last-good fallback. Returns (dict, state).

    Scan failure (unofficial endpoint) or a MIN_MATCH fail-close degrades THAT index to its
    cached last-good value IF still within the freshness window (marked stale=true, shown dated);
    otherwise that index is unavailable. The other index is unaffected. Never raises."""
    try:
        computed = breadth_mod.compute_breadth()
    except Exception as e:
        print(f"breadth: scan failed (non-fatal): {e}")
        computed = {"sp500": None, "ndx100": None}
    lg_all = st.get("breadth_last_good") or {}
    if "value" in lg_all:                       # migrate the pre-two-index flat cache (S&P-only)
        lg_all = {"sp500": lg_all}
    out, new_lg = {}, dict(lg_all)
    for key in ("sp500", "ndx100"):
        b = computed.get(key)
        if b is not None:
            new_lg[key] = dict(b)
            out[key] = {**b, "stale": False}
            continue
        lg = lg_all.get(key)
        if lg:
            gap = state.weekdays_between(lg.get("asof"), today)
            if gap is not None and gap <= config.BREADTH_STALE_TRADING_DAYS:
                print(f"breadth[{key}]: serving last-good value from {lg.get('asof')} (stale)")
                out[key] = {**lg, "stale": True}
                continue
        out[key] = None
    return out, {**st, "breadth_last_good": new_lg}


def _one_breadth_block(b):
    if not b or b.get("value") is None:
        return {"value": None, "asof": None, "status": "unavailable", "matched": 0, "stale": False}
    v = b["value"]
    # Status bands mirror the ALERT tiers: oversold <30 (daily nag zone), watch <40 (the one-shot
    # warning zone), healthy >=40.
    status = ("oversold" if v < config.BREADTH_OVERSOLD
              else "watch" if v < config.BREADTH_WARN else "healthy")
    return {"value": v, "asof": b.get("asof"), "status": status,
            "matched": b.get("matched", 0), "stale": bool(b.get("stale"))}


def _breadth_block(breadth):
    breadth = breadth or {}
    return {"sp500": _one_breadth_block(breadth.get("sp500")),
            "ndx100": _one_breadth_block(breadth.get("ndx100"))}


def _new_policy_items(selected, candidates, seen):
    """Drop already-reported selections, then cut to the rendered cap.

    Returns (items, reported_candidates) — the items to publish, in the model's ranking order, and
    the candidate dicts behind them (what `record_policy` marks seen).

    THIS IS WHERE THE SEEN-SET DEDUPE LIVES. `data/policy.get_policy()` deliberately sends the whole
    prefiltered window to the model, already-reported documents included, because a batch is the only
    mode the model ranks well in (see that module's docstring and CI run 30851392524). The cost of
    that is exactly this: the ranked list can contain documents the user was already told about, and
    they must not ship twice. `summarize_policy` therefore returns up to MAX_POLICY_SELECTIONS (6)
    and the cut to MAX_POLICY_ITEMS (3) happens HERE, AFTER the drop — cutting first would let three
    old items consume the whole section on a day a new rule landed.

    The join is by candidate URL through `summarize._norm_url`, the same join the validator used to
    build these items (it re-takes `url` from the candidate verbatim, so this is an exact match in
    practice; normalizing both sides costs nothing and cannot regress with it). An item that joins to
    nothing cannot be checked against the seen set and is DROPPED, not published: `_validate_policy_
    items` already guarantees every surviving item joins, so a miss here means the join broke, and
    publishing an item whose candidate is unknown would also mean recording nothing as seen for it —
    i.e. re-publishing it every day.
    """
    by_norm = {summarize_mod._norm_url(c.get("url")): c for c in candidates}
    items, reported, repeats, dupes, orphans = [], [], [], [], []
    picked = set()
    for it in selected:
        src = by_norm.get(summarize_mod._norm_url(it.get("url")))
        if src is None:
            orphans.append(it.get("url"))
            continue
        if src["id"] in seen:
            repeats.append(src["id"])
            continue
        # `seen` covers earlier DAYS; `picked` covers this response. Asking for 6 items instead of 3
        # makes a repeated citation likelier, and nothing upstream dedupes: _validate_policy_items
        # joins each item independently, so two items citing one document would render twice.
        # Logged apart from the seen-drop: one is a healthy daily outcome, the other is model noise.
        if src["id"] in picked:
            dupes.append(src["id"])
            continue
        picked.add(src["id"])
        items.append(it)
        reported.append(src)
    if repeats:
        print(f"policy: dropped {len(repeats)} already-reported selection(s): {', '.join(repeats)}")
    if dupes:
        print(f"policy: dropped {len(dupes)} duplicate selection(s) in one response: "
              f"{', '.join(dupes)}")
    for url in orphans:
        print(f"policy: dropped (unjoinable selection): {url}")
    return items[: config.MAX_POLICY_ITEMS], reported[: config.MAX_POLICY_ITEMS]


def _get_policy(st, today):
    """The whole policy leg: re-emit-or-fetch, then record. Returns (items, available, state).

    NEVER raises. main() turns any unhandled exception into a high-priority "briefing run crashed"
    push, so the newest and least critical section must not be able to page the user or cost the
    other sections their run.

    Two orderings in here are load-bearing:

    1. **The same-date re-emit branch runs FIRST, before any fetch.** `_write()` rewrites
       docs/briefing.json AND docs/archive/{date}.json unconditionally, and briefing.yml dispatches
       with `--force` defaulting to true — so a second run of the day is the NORMAL manual path. If
       that run re-fetched and the fetch went badly, it would overwrite the archive with an empty
       policy list and DELETE already-published items. Reading `policy_today` before touching the
       network makes that impossible: no fetch, no model call, no new push.
    2. **Only REPORTED items are marked seen, and only after summarize_policy() returns ok=True.**
       On a model failure nothing is recorded so tomorrow retries; burying a day's candidates
       permanently for a transient Gemini outage is the failure this ordering exists to prevent.
       Staying unseen is only half of it for UTAH: those stubs were already POPPED off
       policy_utah_queue at fetch time and state.save() runs regardless, so the same failure must
       also hand them back via policy_mod.requeue_utah() or they are gone until the next general
       session.

       "Reported, not sent" is a deliberate reversal of the original rule. The seen set is no longer
       an input filter (policy.get_policy sends the whole prefiltered window), so recording
       everything sent would bury the entire window after one call and reproduce the old defect in a
       worse form. The consequence is intended: a candidate the model never selects comes back
       tomorrow instead of being buried unread.

       The ONE exception is the bootstrap suppression below, which marks candidates seen precisely
       *because* it is refusing to report them. Those ids stay in the window and are re-sent, but
       _new_policy_items() drops them after selection, so the suppression still holds.
    """
    candidates = []
    try:
        block = st.get("policy_today") or {}
        if block.get("date") == today:
            items = list(block.get("items") or [])
            # `available` is True, not the (absent) fetch result: nothing was fetched, and the
            # published content is intact — flagging a healthy rebuild as degraded would be a lie.
            print(f"policy: same-date rebuild for {today} — re-emitting {len(items)} item(s) "
                  f"verbatim (no fetch, no model call, no new push)")
            return items, True, state.record_policy(st, [], items, today)

        fetched, st = policy_mod.get_policy(st, today)
        candidates = list(fetched.get("candidates") or [])
        available = bool(fetched.get("available"))

        mark_seen = []
        if not st.get("policy_bootstrapped") and available:
            # First-ever policy run: the 45-day federal window is ALL "new", and back-announcing a
            # month and a half of rules is not a briefing. Mark the federal candidates seen and
            # report none of them. The UTAH QUEUE IS EXEMPT — blanket suppression would swallow the
            # 21 proven-relevant signed 2026GS bills and leave Utah contributing nothing until the
            # next general session in March 2027, killing the higher-signal half for ~7 months.
            # Gated on `available`: bootstrapping off a FAILED federal fetch would mark nothing seen
            # and then back-announce the whole backfill tomorrow — the suppression's exact opposite.
            mark_seen = [c for c in candidates if c.get("source") != "Utah Legislature"]
            candidates = [c for c in candidates if c.get("source") == "Utah Legislature"]
            st = {**st, "policy_bootstrapped": True}
            print(f"policy: bootstrap run — marking {len(mark_seen)} federal candidate(s) seen "
                  f"without reporting; {len(candidates)} Utah candidate(s) still flow normally")

        if not candidates:
            items = []
            print("policy: 0 candidates, skipping model call")
        else:
            selected, ok = summarize_mod.summarize_policy(candidates)
            if ok:
                items, reported = _new_policy_items(selected, candidates,
                                                    st.get("policy_seen") or {})
                mark_seen = mark_seen + reported
                print(f"policy: sent {len(candidates)} candidates, model selected {len(selected)}, "
                      f"{len(items)} new after the already-reported drop")
            else:
                items = []
                st = policy_mod.requeue_utah(st, candidates)
                print(f"policy: model leg did not complete — {len(candidates)} candidate(s) left "
                      f"UNSEEN for tomorrow's retry")

        st = state.record_policy(st, mark_seen, items, today)
        print(f"policy: reported {len(items)}")
        return items, available, st
    except Exception as e:
        # Last-resort guard. Every callee above already promises not to raise; this exists so that a
        # promise broken later degrades ONE section instead of crashing the briefing. Nothing was
        # recorded, so any already-popped Utah candidates go back on the queue for the same reason as
        # the ok=False branch (`candidates` is [] until the fetch returns, so this is a no-op early).
        print(f"policy: leg failed (non-fatal): {type(e).__name__}: {e}")
        return [], False, policy_mod.requeue_utah(st, candidates)


def _fallback_items(news, bucket, limit):
    return [{"summary": a["title"], "source": a["source"], "url": a["url"]}
            for a in news.get(bucket, [])[:limit]]


def _assemble(now, today, market, news, narrative, ai_ok, breadth=None,
              policy=None, policy_upcoming=None, mortgage=None, policy_available=True):
    """`policy`, `policy_upcoming` and `mortgage` are KEYWORD-only in practice (the 7 positional
    args are the pre-existing call shape) and are emitted OUTSIDE the `if ai_ok:` branch: they come
    from a separate model call and a deterministic fetch, and both can succeed on a day when
    summarize() fails."""
    briefing_date = today
    avail = {**market["availability"], **{f"news_{k}": v for k, v in news["available"].items()},
             "summary": "ok" if ai_ok else "unavailable",
             "breadth": bool(breadth and all(
                 breadth.get(k) and breadth[k].get("value") is not None
                 for k in ("sp500", "ndx100"))),
             "policy": bool(policy_available),
             # NOTE: `mortgage` is deliberately NOT part of the markets_ok tuple in run() — PMMS is
             # a WEEKLY release, so a normal publishing gap would fire the high-priority
             # "market data unavailable N days running" escalation.
             "mortgage": mortgage is not None}

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
        "breadth": _breadth_block(breadth),
        "mortgage": mortgage,
        "policy": list(policy or []),
        "policy_upcoming": list(policy_upcoming or []),
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
    mortgage = mortgage_mod.get_rate()      # weekly PMMS release; None on any failure
    news = news_mod.get_news()
    breadth, st = _get_breadth(st, today)   # degradable; may refresh st.breadth_last_good
    # AFTER the breadth reassignment: _get_breadth returns a NEW state dict, so calling the policy
    # leg with the pre-breadth `st` would silently discard breadth_last_good. The chain stays intact.
    policy, policy_available, st = _get_policy(st, today)
    # Already-reported items whose date is still ahead. None-safe: `effective_date` is legitimately
    # null on proposed rules, and `None > "2026-08-03"` raises TypeError, which would kill the run.
    policy_upcoming = [i for i in (st.get("policy_active") or [])
                       if i.get("effective_date") and i["effective_date"] > today]

    # Derive the weekday from the gate date so the build decision, the saved briefing date, and the
    # Sunday-recap choice all agree even if midnight crosses between _now() reads.
    is_sunday = date.fromisoformat(today).weekday() == 6
    narrative, ai_ok = summarize_mod.summarize(
        market, news, is_sunday, recap_context=_recap_context() if is_sunday else "")

    briefing = _assemble(now, today, market, news, narrative, ai_ok, breadth,
                         policy=policy, policy_upcoming=policy_upcoming, mortgage=mortgage,
                         policy_available=policy_available)
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

    # Breadth alerts (warning + oversold tiers, per index): evaluated (and counters/arming
    # advanced) only when this run actually notifies — a --local/--no-notify run must not consume
    # alerts it never delivered.
    #
    # The policy alert follows the same rule and for the same reason. Its state write (record_policy)
    # already happened above on EVERY run — only the ALERT is gated here, and eval_policy_alert reads
    # the `policy_today` block record_policy just wrote, so the order (record, then eval) is required.
    breadth_alerts, policy_alerts = [], []
    if do_notify:
        breadth_alerts, st = state.eval_breadth_alert(breadth, st, today)
        policy_alerts, st = state.eval_policy_alert(policy, st, today)
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

    # Audio edition (non-fatal): generate() swallows its own failures and returns False. A failed
    # audio day just means no manifest gets written downstream and the PWA's Listen button falls
    # back to the on-device voice — the page, push, and state above are already safe on disk.
    audio_ok = tts_mod.generate(briefing)

    # health: report any degraded section (low priority); the run still succeeded
    degraded = [k for k, v in briefing["data_availability"].items()
                if v is False or v == "unavailable"]
    if not audio_ok:
        degraded.append("audio")
    if do_notify:
        for a in breadth_alerts:
            notify.breadth_alert(a["text"], a["level"])
        for a in policy_alerts:
            notify.policy_alert(a["text"])
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
    try:
        print("breadth:", breadth_mod.compute_breadth())
    except Exception as e:
        print("breadth: FAILED —", e)
    print("news candidates: world=%d business=%d tech=%d" %
          (len(n["world"]), len(n["business"]), len(n["tech"])))
    # Federal leg ONLY, and deliberately not via get_policy(): that would run the annual Utah
    # harvest (a 491-row scrape) plus up to MAX_POLICY_ITEMS bill-detail fetches and touch state.
    # data-smoke.yml greps this output under a job timeout, so the spine must stay one request.
    try:
        fed = policy_mod._federal_candidates()
        print("policy candidates: federal=%d (pass prefilter=%d)" %
              (len(fed), sum(1 for c in fed if policy_mod._matches_profile(c))))
    except Exception as e:
        print("policy: FAILED —", e)


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
