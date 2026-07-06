"""Persisted run state (committed to the repo, not served on Pages).

v1 keys: `last_run` (always rewritten to today so there is a daily renewing commit, which keeps
the scheduled GitHub Actions workflow from auto-disabling after 60 idle days), `markets_last_ok`
(last date all four market numbers were present), and `markets_first_bad` (anchor for a blackout
that began with no healthy baseline; cleared on the next healthy day). v2 breadth alert state
will live here too.
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
