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
    """Oversold nag with hysteresis: enter < BREADTH_OVERSOLD, clear >= BREADTH_CLEAR (no
    flapping in the 30-33 band), extreme < BREADTH_EXTREME flagged in the text, and a freshness
    gate — a value older than BREADTH_STALE_TRADING_DAYS latches state but never nags (one stale
    cache value must not page daily). Returns (alert_message_or_None, new_state); breadth
    unavailable -> no state change at all."""
    if not breadth or breadth.get("value") is None:
        return None, st
    b = st.get("breadth", {"in_alert": False, "nag_days": 0})
    val, asof = breadth["value"], breadth.get("asof")
    upd = {**b, "last_value": val, "last_asof": asof}
    if val < config.BREADTH_OVERSOLD:
        upd["in_alert"] = True
        gap = weekdays_between(asof, today)
        if gap is None or gap > config.BREADTH_STALE_TRADING_DAYS:
            return None, {**st, "breadth": upd}
        upd["nag_days"] = b.get("nag_days", 0) + 1
        extreme = " (EXTREME)" if val < config.BREADTH_EXTREME else ""
        return (f"S&P 500 breadth: {val}% of stocks above their 200-day average — "
                f"oversold{extreme}, day {upd['nag_days']}. Bullish-reversal watch zone.",
                {**st, "breadth": upd})
    if b.get("in_alert") and val < config.BREADTH_CLEAR:
        return None, {**st, "breadth": {**upd, "in_alert": True}}   # latched: 30-33 wobble stays quiet
    return None, {**st, "breadth": {**upd, "in_alert": False, "nag_days": 0}}


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
