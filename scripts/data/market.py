"""Headline market numbers for v1: S&P 500, Nasdaq (Composite), VIX, 10-year Treasury yield.

All four come from Yahoo Finance's keyless chart API. Unlike most free tiers (incl. Twelve Data),
Yahoo's chart endpoint includes indices, so it can serve all four with no key. We request a short
recent daily window and use the last two daily closes as prior-close / day-over-day values.

Each number is returned as {value, change, asof}:
- value : latest close
- change: latest close minus the previous close (in the number's own units)
- asof  : the trading date the value belongs to (YYYY-MM-DD)
Missing data degrades to None rather than raising, so the briefing still ships.
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .. import config

# Yahoo's chart endpoint rejects some non-browser User-Agents; use a browser-like UA.
YAHOO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _parse(data):
    """Pull the last two daily closes out of a Yahoo chart payload -> {value, change, asof} or None."""
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    points = [(t, c) for t, c in zip(ts, closes) if c is not None]   # drop nulls (holidays/gaps)
    if not points:
        return None
    last_t, last_val = points[-1]
    prev_val = points[-2][1] if len(points) >= 2 else last_val
    asof = datetime.fromtimestamp(last_t, tz=timezone.utc).date().isoformat()
    return {"value": round(last_val, 2), "change": round(last_val - prev_val, 2), "asof": asof}


def _yahoo_series(symbol, retries=1):
    """Return {value, change, asof} for a symbol via Yahoo's chart API, or None.

    Tries the query1 then query2 host on each attempt (one is often up when the other rate-limits),
    with a short timeout so a hung source can't blow the job timeout."""
    url_tmpl = config.YAHOO_CHART
    last_err = None
    for attempt in range(retries + 1):
        for host in ("query1", "query2"):
            url = url_tmpl.format(host=host, symbol=urllib.parse.quote(symbol))
            req = urllib.request.Request(
                url, headers={"User-Agent": YAHOO_UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=config.MARKET_TIMEOUT) as r:
                    return _parse(json.loads(r.read().decode()))
            except Exception as e:
                last_err = e
                continue
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    # Log the real reason — a silent None made the FRED outage invisible for days.
    print(f"market: Yahoo {symbol} failed: {type(last_err).__name__}: {last_err}")
    return None


def get_market():
    """Return the four headline numbers + an availability map. Each value may be None."""
    out, avail = {}, {}
    for key, symbol in config.YAHOO_SYMBOLS.items():
        try:
            out[key] = _yahoo_series(symbol)
        except Exception:
            out[key] = None
        avail[key] = out[key] is not None
    return {
        "sp500": out.get("sp500"),
        "ndx": out.get("ndx"),          # Nasdaq Composite (labeled "Nasdaq" in the UI)
        "vix": out.get("vix"),
        "ten_year": out.get("ten_year"),
        "availability": avail,
    }
