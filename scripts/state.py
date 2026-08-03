"""Persisted run state (committed to the repo, not served on Pages).

v1 keys: `last_run` (always rewritten to today so there is a daily renewing commit, which keeps
the scheduled GitHub Actions workflow from auto-disabling after 60 idle days), `markets_last_ok`
(last date all four market numbers were present), and `markets_first_bad` (anchor for a blackout
that began with no healthy baseline; cleared on the next healthy day). v2 breadth alert state
will live here too.

Policy keys (v3), all written by `record_policy()` — the single writer:

- `policy_seen` `{candidate_id: publication_date}` — every candidate that was actually REPORTED to
  the user (plus the first run's bootstrap-suppressed federal window, which is marked seen precisely
  because it is being withheld). It is NOT everything sent to the model: since 2026-08-03 the model
  is handed the whole prefiltered window every day, and `build_briefing._new_policy_items()` drops
  already-reported ids AFTER the model has ranked. Read there, and by
  `policy._maybe_harvest_utah()` to avoid re-queueing a bill that was already reported.
  Never pruned: ~200 entries a year in a file rewritten daily, and an eviction rule interacting
  with the 45-day fetch window is a hazard for no benefit.
- `policy_active` `[item]` — already-reported items whose `effective_date` is still in the future.
  Deduped by url, sorted ascending, capped at `config.MAX_POLICY_UPCOMING`. Projected to
  `policy_upcoming` in the briefing. `effective_date` is legitimately null on proposed rules, so
  every comparison here is None-safe (`None > "2026-08-03"` raises TypeError in Python 3).
- `policy_today` `{date, items, alerted}` — the day's reported items, replaced only when the stored
  date differs from today, so a `--force` same-date rebuild re-emits verbatim and keeps the
  `alerted` stamp. `eval_policy_alert()` flips that one stamp and touches nothing else.
"""
import json
import os

from . import config


def weekdays_between(a_iso, b_iso):
    """Trading-day distance approximation (weekends only, holidays ignored — a holiday makes a
    value look at most one day staler, which errs toward SUPPRESSING a nag, the safe direction).
    None when either date is missing/unparseable."""
    from datetime import date, timedelta
    try:
        a, b = date.fromisoformat(a_iso), date.fromisoformat(b_iso)
    except (TypeError, ValueError):
        return None
    if a > b:
        return 0
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def eval_breadth_alert(breadth, st, today):
    """Two alert tiers, evaluated independently per index (sp500, ndx100):

    - WARNING (one-shot): fires once when breadth FALLS below BREADTH_WARN (40); re-armed only
      after recovering to BREADTH_WARN_CLEAR (42), so a 39/41 wobble can't repeat it.
    - OVERSOLD (daily nag): below BREADTH_OVERSOLD (30) it pages every notifying run with a day
      counter, clears at BREADTH_CLEAR (33); below BREADTH_EXTREME (20) flagged EXTREME. Being
      oversold supersedes the warning tier (no double-page on the way down).

    Both tiers are freshness-gated: a value older than BREADTH_STALE_TRADING_DAYS updates state
    but never notifies (one stale cache value must not page daily). Returns (alerts, new_state)
    where alerts is a list of {"level": "warning"|"oversold", "text": ...}; an unavailable index
    leaves its state untouched."""
    if not breadth:
        return [], st
    cur = st.get("breadth") or {}
    if "in_alert" in cur:                       # migrate the pre-two-index flat shape (S&P-only)
        cur = {"sp500": cur}
    alerts, out = [], dict(cur)
    for key, label in (("sp500", "S&P 500"), ("ndx100", "Nasdaq-100")):
        b = breadth.get(key)
        if not b or b.get("value") is None:
            continue
        s = {**{"in_alert": False, "nag_days": 0, "warn_armed": True}, **out.get(key, {})}
        val, asof = b["value"], b.get("asof")
        s.update(last_value=val, last_asof=asof)
        gap = weekdays_between(asof, today)
        stale = gap is None or gap > config.BREADTH_STALE_TRADING_DAYS
        if val < config.BREADTH_OVERSOLD:
            s["in_alert"] = True
            s["warn_armed"] = False             # superseded; re-arms only at WARN_CLEAR
            if not stale:
                s["nag_days"] = s.get("nag_days", 0) + 1
                extreme = " (EXTREME)" if val < config.BREADTH_EXTREME else ""
                alerts.append({"level": "oversold", "text":
                    f"{label} breadth: {val}% of stocks above their 200-day average — "
                    f"oversold{extreme}, day {s['nag_days']}. Bullish-reversal watch zone."})
        elif s.get("in_alert") and val < config.BREADTH_CLEAR:
            pass                                # latched: 30-33 wobble stays quiet
        else:
            s["in_alert"] = False
            s["nag_days"] = 0
            if val >= config.BREADTH_WARN_CLEAR:
                s["warn_armed"] = True
            elif s.get("warn_armed") and val < config.BREADTH_WARN and not stale:
                s["warn_armed"] = False
                alerts.append({"level": "warning", "text":
                    f"{label} breadth fell below {config.BREADTH_WARN}%: {val}% of stocks above "
                    f"their 200-day average — weakening participation."})
        out[key] = s
    return alerts, {**st, "breadth": out}


def record_policy(st, mark_seen, reported, today):
    """The SINGLE writer of every policy state key. Returns the new state (pure, no I/O).

    `mark_seen` is the CANDIDATE dicts to burn into `policy_seen`: the ones actually reported today,
    plus the first-run bootstrap's deliberately-suppressed federal window. It is NOT "everything
    sent" — that was the pre-2026-08-03 rule and it is gone, because `data/policy.get_policy()` now
    hands the model the whole prefiltered window every day and recording all of it would bury the
    window after a single call. Callers pass `[]` when nothing should be burned (a failed model call
    must leave its candidates unseen so tomorrow retries; a same-date re-emit already recorded its
    items on the first run of the day).
    `reported` is every item that survived validation and is being published today.

    Two earlier revisions of this feature shipped a policy field that was declared and read but
    never written; funnelling all three keys through one function is why that cannot recur.
    """
    seen = dict(st.get("policy_seen") or {})
    for c in mark_seen or []:
        seen[c["id"]] = c.get("published") or today

    # None-safe: `effective_date` is null on proposed rules, and a bare `>` against None raises.
    active = [i for i in list(st.get("policy_active") or []) + list(reported or [])
              if i.get("effective_date") and i["effective_date"] > today]
    active = sorted({i.get("url"): i for i in active}.values(),
                    key=lambda i: i["effective_date"])[:config.MAX_POLICY_UPCOMING]

    today_block = st.get("policy_today") or {}
    if today_block.get("date") != today:      # same-date rebuild keeps items AND the alerted stamp
        today_block = {"date": today, "items": list(reported or []), "alerted": False}
    return {**st, "policy_seen": seen, "policy_active": active, "policy_today": today_block}


def eval_policy_alert(items, st, today):
    """One push per newly-reported FINAL rule. Returns (alerts, new_state), same shape as
    `eval_breadth_alert` — a list of {"level", "text"} plus the state to carry forward.

    Never alerts on a `Proposed` rule (nothing has taken effect yet) and never on `Signed in Utah`
    (the Utah queue is an annual backfill released a few items a day, not news — the brief locks
    pushes to "rare, ~monthly"). The `policy_today.alerted` stamp makes the push one-shot per date,
    which matters because `briefing.yml:50-51` dispatches with `--force` defaulting to true, so a
    same-date rerun is the normal manual path and must not re-push."""
    block = st.get("policy_today") or {}
    if block.get("date") != today:            # a stale block's stamp must not gag a new day
        block = {"date": today, "items": list(items or []), "alerted": False}
    if block.get("alerted"):
        return [], st

    alerts = []
    for it in items or []:
        if it.get("status") != "Final rule":
            continue
        what = (it.get("what_happened") or "").strip() or it.get("url") or "a new federal rule"
        eff = it.get("effective_date")
        when = f"Effective {eff}." if eff else "No effective date published yet."
        alerts.append({"level": "policy", "text": f"New final rule: {what} {when}"})
    if not alerts:
        return [], st
    return alerts, {**st, "policy_today": {**block, "alerted": True}}


def load():
    try:
        with open(config.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_run": None}  # cold-start default


def save(state, today):
    state = {**state, "last_run": today}  # always refresh → guarantees a daily commit
    os.makedirs(os.path.dirname(config.STATE_PATH), exist_ok=True)
    with open(config.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return state
