"""Leveraged ETF pulse: where SOXL / SPXL / TQQQ sit in their own recent range.

Read once a day, near the top of the briefing. The point is orientation, not a trade: is this
thing stretched, beaten down, or in the middle of its own month?

Two independent readings per ticker, both computed here from the SAME Yahoo daily closes the four
headline market numbers come from (no new source, no key, no scrape):

  RSI-14, Wilder smoothing - the oscillator Webull and TradingView draw, with the conventional
  30/70 lines. Cross-validated 2026-09-09 against TradingView's published RSI column while the US
  session was open: SOXL 50.27 vs 50.14, SPXL 46.97 vs 46.73, TQQQ 50.19 vs 50.20. The residual is
  live intraday drift (TradingView was quoting the in-progress bar this module deliberately drops),
  so the agreement is tighter than a quarter point, not looser.

  Position in the 1-month CLOSING band, with the zone thresholds the reader's old hourly ETF
  monitor actually fired on: bottom zone at close <= low * 1.04, top zone at close >= high * 0.96.
  Closes, not intraday extremes, because closes are what this series carries - stated in the UI
  rather than papered over.

Everything here is deterministic. No model touches these numbers, which is also why the section
survives a day when Gemini is down (see build_briefing._assemble: it is emitted outside `if ai_ok`).

FAIL CLOSED, PER TICKER. A dead fetch, too few bars, or a zero-width band returns None for THAT
ticker; the other two still publish. A confidently wrong RSI is worse than an absent one - this is
the same rule breadth follows, and for the same reason.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .. import config
from . import market


def rsi_wilder(closes, period=None):
    """Wilder's RSI over a list of closes (oldest first). None when there is not enough history.

    Wilder's average is SEEDED (a simple mean of the first `period` changes) and then smoothed
    forward over every remaining bar - it is not a rolling window. So the answer depends on how far
    back the series starts, and a short series returns a wrong number rather than no number. That
    is what LEVERAGED_MIN_BARS guards at the caller; this function only refuses the arithmetically
    impossible case.
    """
    period = period or config.RSI_PERIOD
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        # An unbroken run of up days. RSI is 100 by definition; the ratio would divide by zero.
        # A dead-flat series has no gains either - that is 50, not 100.
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_zone(rsi):
    """'oversold' | 'overbought' | 'neutral' - the 30/70 lines, or None for a missing RSI."""
    if rsi is None:
        return None
    if rsi < config.RSI_OVERSOLD:
        return "oversold"
    if rsi > config.RSI_OVERBOUGHT:
        return "overbought"
    return "neutral"


def band_zone(close, low, high):
    """'low' | 'high' | 'mid' - the old hourly monitor's add/trim thresholds, level-triggered.

    Order matters on a squeezed band: a range narrow enough that both tests pass is far more often
    a collapsed range than a genuine top, so the bottom zone is checked first."""
    if close is None or low is None or high is None:
        return None
    if close <= low * (1 + config.LEVERAGED_LOW_BAND):
        return "low"
    if close >= high * (1 - config.LEVERAGED_HIGH_BAND):
        return "high"
    return "mid"


def band_position(close, low, high):
    """Where the close sits across the band, 0 (at the low) to 100 (at the high). None if flat.

    A zero-width band is a degenerate month (one bar, or a halted ticker), not a midpoint - return
    None rather than a fabricated 50."""
    if close is None or low is None or high is None or high <= low:
        return None
    return round(100.0 * (close - low) / (high - low), 1)


def _read(rsi_z, band_z, pct, day_move):
    """The one-line plain-English read. Deterministic: it says what the numbers say and stops.

    Written in code rather than by the model on purpose. Every figure in this section is already
    computed and exact, and a model asked to narrate exact figures is a model given the chance to
    restate one of them wrongly. It also keeps the section honest on a no-AI day."""
    big = day_move is not None and abs(day_move) >= config.LEVERAGED_MOVER_PCT
    swing = (" Big session: {} {:.1f}% in a day.".format(
        "up" if day_move > 0 else "down", abs(day_move))) if big else ""
    low_pct = "{:.0%}".format(config.LEVERAGED_LOW_BAND)
    high_pct = "{:.0%}".format(config.LEVERAGED_HIGH_BAND)

    if band_z == "low" and rsi_z == "oversold":
        return "Near the bottom of its 1-month range and oversold on RSI." + swing
    if band_z == "low":
        return "Within {} of its 1-month low.".format(low_pct) + swing
    if band_z == "high" and rsi_z == "overbought":
        return "Within {} of its 1-month high and overbought on RSI.".format(high_pct) + swing
    if band_z == "high":
        return "Within {} of its 1-month high.".format(high_pct) + swing
    if rsi_z == "oversold":
        return "Oversold on RSI, mid-range for the month." + swing
    if rsi_z == "overbought":
        return "Overbought on RSI, mid-range for the month." + swing
    if pct is not None:
        return "Mid-range - {:.0f}% of the way up its 1-month band.".format(pct) + swing
    return "Mid-range for the month." + swing


def _series(symbol):
    """Settled daily closes for one symbol via Yahoo's chart API -> [(epoch, close)] or None.

    Mirrors market._yahoo_series: same UA, same two-host fallback, same timeout, same rule about
    dropping an in-progress session's live bar. A partial bar here would poison BOTH readings - it
    would enter the RSI chain as today's close and could set a band extreme."""
    last_err = None
    for host in ("query1", "query2"):
        url = config.YAHOO_CHART.format(host=host, symbol=urllib.parse.quote(symbol),
                                        range=config.YAHOO_RANGE_HISTORY)
        req = urllib.request.Request(
            url, headers={"User-Agent": market.YAHOO_UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=config.MARKET_TIMEOUT) as r:
                data = json.loads(r.read().decode())
            res = data["chart"]["result"][0]
            points = [(t, c) for t, c in zip(res["timestamp"],
                                             res["indicators"]["quote"][0]["close"])
                      if c is not None]
            points = market.drop_open_session_bar(points, res.get("meta") or {})
            if points:
                return points
            # HTTP 200 with an unusable series is a failure, not an absence - say so, and let the
            # other host still try. A silent None is how the FRED outage stayed invisible for days.
            last_err = ValueError("valid response but empty/unusable chart series")
        except Exception as e:
            last_err = e
    print("leveraged: Yahoo {} failed: {}: {}".format(symbol, type(last_err).__name__, last_err))
    return None


def read_ticker(symbol, what):
    """One ticker's full reading, or None if anything about it is untrustworthy."""
    points = _series(symbol)
    if not points:
        return None
    closes = [c for _, c in points]
    if len(closes) < config.LEVERAGED_MIN_BARS:
        print("leveraged[{}]: only {} settled bars (< {}) - failing closed rather than seeding "
              "RSI short".format(symbol, len(closes), config.LEVERAGED_MIN_BARS))
        return None

    close = closes[-1]
    prev = closes[-2]
    change = round(close - prev, 2)
    day_move = (100.0 * (close - prev) / prev) if prev else None

    window = closes[-config.LEVERAGED_BAND_DAYS:]
    low, high = min(window), max(window)
    rsi = rsi_wilder(closes)
    rsi_z, band_z = rsi_zone(rsi), band_zone(close, low, high)
    pct = band_position(close, low, high)
    asof = datetime.fromtimestamp(points[-1][0], tz=timezone.utc).date().isoformat()

    return {
        "symbol": symbol,
        "what": what,
        "value": round(close, 2),
        "change": change,
        "day_move": round(day_move, 2) if day_move is not None else None,
        "asof": asof,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "rsi_zone": rsi_z,
        "low": round(low, 2),
        "high": round(high, 2),
        "band_pct": pct,
        "zone": band_z,
        "read": _read(rsi_z, band_z, pct, day_move),
    }


def get_leveraged():
    """Every configured ticker, in config order. Entries that failed closed are simply absent."""
    out = []
    for symbol, what in config.LEVERAGED_TICKERS:
        try:
            row = read_ticker(symbol, what)
        except Exception as e:   # one bad ticker must never take the other two down with it
            print("leveraged[{}]: failed (non-fatal): {}: {}".format(
                symbol, type(e).__name__, e))
            row = None
        if row:
            out.append(row)
    return out
