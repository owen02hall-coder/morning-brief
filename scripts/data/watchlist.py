"""Watchlist pulse: where each followed ticker sits in its own recent range.

Read once a day, near the top of the briefing. The point is orientation, not a trade: is this
thing stretched, beaten down, or in the middle of its own month?

The tickers come from watchlist.txt at the repo root (config._load_watchlist), so the list is
the reader's to edit and this module must not assume it is three leveraged ETFs.

Two independent readings per ticker, both computed here from the SAME Yahoo daily closes the four
headline market numbers come from (no new source, no key, no scrape):

  RSI-14, Wilder smoothing - the oscillator Webull and TradingView draw, with the conventional
  30/70 lines. Cross-validated 2026-09-09 against TradingView's published RSI column while the US
  session was open: SOXL 50.27 vs 50.14, SPXL 46.97 vs 46.73, TQQQ 50.19 vs 50.20. The residual is
  live intraday drift (TradingView was quoting the in-progress bar this module deliberately drops),
  so the agreement is tighter than a quarter point, not looser.

  Position in the 1-month CLOSING band, with the zone thresholds the reader's old hourly ETF
  monitor actually fired on: bottom zone at close <= low * 1.04, top zone at close >= high * 0.96,
  each additionally gated on being in the bottom/top third of the band (see band_zone - the bare
  percent rule stops discriminating once a calm, non-3x ticker joins the list).
  Closes, not intraday extremes, because closes are what this series carries - stated in the UI
  rather than papered over.

Those two readings collapse into ONE action - buy / trim / hold (action_zone). That single field
is what the page colours and the only thing the audio speaks, so the page and the mp3 cannot
disagree about what to do: there is one classifier, here, and both surfaces read its answer.

Everything here is deterministic. No model touches these numbers, which is also why the section
survives a day when Gemini is down (see build_briefing._assemble: it is emitted outside `if ai_ok`).

FAIL CLOSED, PER TICKER. A dead fetch, too few bars, or a zero-width band returns None for THAT
ticker; the rest still publish. A confidently wrong RSI is worse than an absent one - this is
the same rule breadth follows, and for the same reason.

But absence is REPORTED, not swallowed: get_watchlist also returns the symbols that were asked
for and produced nothing, and the page names them. The list is hand-edited now, and a mistyped
ticker that simply never appears is indistinguishable from one the reader forgot to add.
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
    is what WATCHLIST_MIN_BARS guards at the caller; this function only refuses the arithmetically
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

    TWO gates, and a zone needs both. The percent gate is the monitor's own rule: the close is
    within WATCHLIST_LOW_BAND of the month's low. The position gate additionally asks that the close
    sit in the bottom third of the band it actually has.

    The second gate exists because the first one silently stops discriminating as volatility falls.
    On a 3x ETF a 4% sliver is a corner of a band that is routinely 30-40% wide. On a calm stock
    whose month spans 7%, low * 1.04 lands near the 60th percentile of the band, so "within 4% of
    the low" would be true most days, and a BUY colour that is on two days in three tells the reader
    nothing. The watchlist is the reader's to edit now, so this module can no longer assume the
    three volatile ETFs it was born on.

    Order matters on a squeezed band: a range narrow enough that both tests pass is far more often
    a collapsed range than a genuine top, so the bottom zone is checked first.

    A degenerate band (high <= low: one settled bar, or a halted ticker) has no position to measure.
    That is unknown, not 'mid' - return None and let the caller publish the RSI alone."""
    if close is None or low is None or high is None:
        return None
    pct = band_position(close, low, high)
    if pct is None:
        return None
    edge = config.WATCHLIST_BAND_EDGE_PCT
    if close <= low * (1 + config.WATCHLIST_LOW_BAND) and pct <= edge:
        return "low"
    if close >= high * (1 - config.WATCHLIST_HIGH_BAND) and pct >= 100.0 - edge:
        return "high"
    return "mid"


ACTION_BUY, ACTION_TRIM, ACTION_HOLD = "buy", "trim", "hold"


def action_zone(rsi_z, band_z):
    """'buy' | 'trim' | 'hold' - the one field the card colours by and the ONLY one the audio reads.

    Either reading on its own is enough to call an action. The band says the price is at the edge of
    its own month; RSI says the move that put it there is stretched. They agree often and fire
    separately sometimes, and the reader's old hourly monitor acted on either.

    A ticker satisfying BOTH sides at once is not a strong signal, it is a contradiction - only
    reachable on a band narrow enough for its edges to overlap, or a violent reversal inside one
    month. That returns hold. An ambiguous signal is not an instruction, and the card's `read` line
    still describes the state truthfully underneath the badge.

    Never None. A ticker with neither a usable RSI nor a usable band is hold: the page must not
    colour a card BUY on the strength of a reading it does not have, and the audio must not name a
    ticker it can say nothing about."""
    buy = band_z == "low" or rsi_z == "oversold"
    trim = band_z == "high" or rsi_z == "overbought"
    if buy and trim:
        return ACTION_HOLD
    if buy:
        return ACTION_BUY
    if trim:
        return ACTION_TRIM
    return ACTION_HOLD


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
    big = day_move is not None and abs(day_move) >= config.WATCHLIST_MOVER_PCT
    swing = (" Big session: {} {:.1f}% in a day.".format(
        "up" if day_move > 0 else "down", abs(day_move))) if big else ""
    low_pct = "{:.0%}".format(config.WATCHLIST_LOW_BAND)
    high_pct = "{:.0%}".format(config.WATCHLIST_HIGH_BAND)

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
    print("watchlist: Yahoo {} failed: {}: {}".format(symbol, type(last_err).__name__, last_err))
    return None


def read_ticker(symbol, what):
    """One ticker's full reading, or None if anything about it is untrustworthy."""
    points = _series(symbol)
    if not points:
        return None
    closes = [c for _, c in points]
    if len(closes) < config.WATCHLIST_MIN_BARS:
        print("watchlist[{}]: only {} settled bars (< {}) - failing closed rather than seeding "
              "RSI short".format(symbol, len(closes), config.WATCHLIST_MIN_BARS))
        return None

    close = closes[-1]
    prev = closes[-2]
    # Percent only. The absolute dollar move was published until 2026-09-09 and read by nothing:
    # on a 3x fund the percent is the meaningful unit, and both the card and the narration use it.
    day_move = (100.0 * (close - prev) / prev) if prev else None

    window = closes[-config.WATCHLIST_BAND_DAYS:]
    low, high = min(window), max(window)
    rsi = rsi_wilder(closes)
    rsi_z, band_z = rsi_zone(rsi), band_zone(close, low, high)
    pct = band_position(close, low, high)
    asof = datetime.fromtimestamp(points[-1][0], tz=timezone.utc).date().isoformat()

    return {
        "symbol": symbol,
        "what": what,
        "value": round(close, 2),
        "day_move": round(day_move, 2) if day_move is not None else None,
        "asof": asof,
        "rsi": round(rsi, 1) if rsi is not None else None,
        "rsi_zone": rsi_z,
        "low": round(low, 2),
        "high": round(high, 2),
        "band_pct": pct,
        "zone": band_z,
        # Classified HERE, once, and carried in the JSON. The card colour and the spoken line both
        # read this field rather than re-deriving it from rsi_zone/zone, so a change to the rule
        # cannot leave the page saying BUY while the mp3 says nothing at all.
        "action": action_zone(rsi_z, band_z),
        "read": _read(rsi_z, band_z, pct, day_move),
    }


def get_watchlist():
    """Every configured ticker, in config order -> (rows, missing).

    `missing` is every symbol that was asked for and produced nothing. It is returned rather than
    discarded because the list is hand-edited in watchlist.txt now: a mistyped symbol fails its
    Yahoo fetch and, if that failure were merely swallowed, would look exactly like a ticker the
    reader forgot to add. No offline check can tell a typo apart from a real symbol - "NOT", left
    behind by the line "not a ticker", parses as cleanly as "TQQQ" - so the fetch is the only
    honest test, and its answer has to reach the page."""
    rows, missing = [], []
    for symbol, what in config.WATCHLIST_TICKERS:
        try:
            row = read_ticker(symbol, what)
        except Exception as e:   # one bad ticker must never take the rest of the list down with it
            print("watchlist[{}]: failed (non-fatal): {}: {}".format(
                symbol, type(e).__name__, e))
            row = None
        if row:
            rows.append(row)
        else:
            missing.append(symbol)
    return rows, missing
