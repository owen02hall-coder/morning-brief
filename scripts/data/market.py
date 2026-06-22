"""Headline market numbers for v1: S&P 500, Nasdaq (Composite), VIX, 10-year Treasury yield.

All four come from FRED's keyless CSV (reliable, no key, no anti-bot) as prior-close /
day-over-day values. We request only a short recent window (FRED_WINDOW_DAYS) so each payload is
tiny and fast — fetching the full multi-decade history was timing out.

Each number is returned as {value, change, asof}:
- value : latest close
- change: latest close minus the previous close (in the number's own units)
- asof  : the trading date the value belongs to (YYYY-MM-DD)
Missing data degrades to None rather than raising, so the briefing still ships.
"""
import csv
import io
import time
import urllib.request
from datetime import date, timedelta

from .. import config

# FRED appears to reject non-browser User-Agents from datacenter IPs (works from a home IP, fails
# from a GitHub Actions runner). Use a browser-like UA for FRED specifically.
FRED_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _fred_series(series_id, retries=1):
    """Return (value, change, asof) from a recent-window FRED CSV, using the last two values."""
    cosd = (date.today() - timedelta(days=config.FRED_WINDOW_DAYS)).isoformat()
    url = config.FRED_CSV.format(series=series_id, cosd=cosd)
    req = urllib.request.Request(url, headers={"User-Agent": FRED_UA, "Accept": "text/csv,*/*"})
    text = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=config.FRED_TIMEOUT) as r:
                text = r.read().decode()
            break
        except Exception as e:
            # Log the real reason (silent None made the runner failure invisible).
            print(f"market: FRED {series_id} attempt {attempt + 1} failed: {type(e).__name__}: {e}")
            if attempt >= retries:
                return None
            time.sleep(2 * (attempt + 1))
    rows = list(csv.reader(io.StringIO(text)))
    points = []
    for row in rows[1:]:                       # skip header
        if len(row) < 2:
            continue
        raw = row[1].strip()
        if raw in ("", "."):                   # holidays / missing
            continue
        try:
            points.append((row[0], float(raw)))
        except ValueError:
            continue
    if not points:
        return None
    last_date, last_val = points[-1]
    prev_val = points[-2][1] if len(points) >= 2 else last_val
    return {"value": round(last_val, 2), "change": round(last_val - prev_val, 2), "asof": last_date}


def get_market():
    """Return the four headline numbers + an availability map. Each value may be None."""
    out, avail = {}, {}
    for key, series in config.FRED_SERIES.items():
        try:
            out[key] = _fred_series(series)
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
