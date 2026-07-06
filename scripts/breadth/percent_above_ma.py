"""Market breadth: % of S&P 500 stocks above their 200-day moving average.

Method (validated locally 2026-06-16 at 62.1% vs published 60.8–62.0, re-validated 2026-07-05):
scan the top BREADTH_SCAN_LIMIT US stocks by market cap for close + SMA200 via TradingView's
scanner endpoint (unofficial, keyless), intersect with Wikipedia's constituent list, and take the
ratio. Fail-closed: if fewer than BREADTH_MIN_MATCH constituents match (scan failure, membership
drift, layout drift), return None — the caller falls back to its last-good cache or shows
"unavailable". A biased number is worse than no number.

The exact StockCharts Bullish Percent Index has no free feed; this is the standard computable
equivalent. The PWA keeps the $BPSPX/$BPNDX links alongside the number.
"""
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config
from ..data import constituents


def last_settled_trading_date():
    """Most recent weekday whose regular session has closed (US/Eastern).

    Naive about market holidays: on the morning after a holiday this can claim the holiday's
    date while the scan value is really the prior session's close — one day of cosmetic
    overstatement, and in the SAFE direction for the alert's staleness gate (it can only make a
    value look at most one day fresher on a holiday week, still inside the 2-day window).
    """
    now = datetime.now(ZoneInfo("America/New_York"))
    d = now.date()
    if now.hour < 16 or d.weekday() >= 5:   # before today's close (or weekend) -> step back
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def percent_above_200ma():
    """Return {value, matched, asof} or None (degraded — caller handles cache/unavailable)."""
    members = constituents.sp500_symbols()
    body = json.dumps({
        "columns": ["name", "close", "SMA200"],
        # type=stock is load-bearing: without it ~430 ADR/fund rows displace S&P names out of
        # the top-N and coverage collapses to ~410 (below the MIN_MATCH gate).
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, config.BREADTH_SCAN_LIMIT],
    }).encode()
    req = urllib.request.Request(
        config.BREADTH_SCAN_URL, data=body, method="POST",
        headers={"User-Agent": config.USER_AGENT, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.loads(r.read().decode()).get("data", [])

    keys = {s.upper().replace(".", "") for s in members}   # BRK.B <-> BRKB normalization
    above = total = 0
    seen = set()
    for row in rows:
        d = row.get("d") or []
        if len(d) < 3 or d[1] is None or d[2] is None:
            continue
        k = str(d[0]).upper().replace(".", "")
        if k in keys and k not in seen:                    # dual-listings: count each name once
            seen.add(k)
            total += 1
            if d[1] > d[2]:
                above += 1
    if total < config.BREADTH_MIN_MATCH:
        print(f"breadth: only {total} constituents matched (< {config.BREADTH_MIN_MATCH}) — failing closed")
        return None
    return {"value": round(100 * above / total, 1), "matched": total,
            "asof": last_settled_trading_date()}
