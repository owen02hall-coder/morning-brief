"""Freddie Mac PMMS 30-year fixed mortgage rate — the one part of the policy feature with content
52 weeks a year, and the single most house-buying-relevant number available.

Freddie Mac publishes the Primary Mortgage Market Survey as a plain history CSV (2,889 rows as of
2026-07-30). The header is `date,pmms30,pmms30p,pmms15,...` and rows are oldest-first with `M/D/YYYY`
dates, so the LAST row is the current release. The 30-year rate is read by COLUMN NAME, never by
position, so an inserted column shifts nothing.

get_rate() returns {value, change, asof} or None:
- value : the 30-year fixed rate as a float (e.g. 6.66)
- change: this release minus the PREVIOUS release, in percentage points (e.g. -0.03), or None when
          the file holds no prior row — never a fabricated 0.0, the same rule market.py follows for
          a lone settled close. Rate DIRECTION is what a first-time buyer is actually deciding on,
          and the prior week's row is already in memory when the file parses.
- asof  : the release date that rate belongs to (YYYY-MM-DD)

The survey is released WEEKLY (Thursday), so on most mornings the newest row is several days old —
that is this source's normal state, not staleness. There is deliberately NO freshness guard here: one
would fire every Monday and turn a healthy feed into a false alarm. A genuinely stalled feed, a moved
column or a changed date format is caught instead by the weekly assumption gate
(`scripts/briefing-assumptions/05-policy-sources.py` P4, which bounds the row age at 14 days).

Any failure degrades to None rather than raising, so the briefing still ships.
"""
import csv
import io
import urllib.request
from datetime import date, datetime

from .. import config
from . import retry

# freddiemac.com answers this path for a browser-like User-Agent; the project UA is unprobed there,
# and 05-policy-sources.py proved P4 against the live file using exactly this shape. Module-local on
# purpose, following market.YAHOO_UA: it is a property of THIS host's bot filtering, not a project
# identity, so it must not migrate into config.py where it would read as the global UA.
PMMS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# The history file is ~150 KB and grows ~4 KB/year, so this is ~25x headroom. It exists only to bound
# a pathological response; hitting it is treated as an error, never as data (see get_rate).
_READ_CAP = 4_000_000


def _rate_at(row, col):
    """The 30-year rate in one already-split CSV row, or None if that cell is missing/blank/junk.

    Only used for the PRIOR row. The NEWEST row is deliberately NOT read through here: a missing
    rate there means there is no rate to publish at all, which must raise into get_rate()'s logged
    degrade, not quietly become None."""
    try:
        return float(_cell(row[col]))
    except (IndexError, ValueError):
        return None


def _cell(s):
    """One CSV cell with stray quotes, whitespace and a byte-order mark removed.

    csv.reader already unwraps properly quoted cells. The extra strip is for a half-quoted cell or a
    BOM on the first header name, either of which would otherwise turn a healthy file into a parse
    failure the same way the quoted dates did on 2026-11-25."""
    return (s or "").strip().lstrip("﻿").strip().strip('"').strip()


def _rows(raw):
    """The non-empty rows of a PMMS history CSV, split by the csv module.

    NOT str.split(","). On 2026-11-25 Freddie Mac started quoting the data cells ("11/25/2026"), and
    the old split handed strptime a date wrapped in quote marks. Both runs that day shipped with no
    mortgage rate. csv.reader handles quoted and unquoted files identically, and a quoted cell that
    contains a comma (which split would cut in two) as well."""
    return [r for r in csv.reader(io.StringIO(raw)) if any(_cell(c) for c in r)]


def _parse(raw):
    """Pull the newest 30-year rate + its week-over-week move out of a PMMS history CSV.

    -> {value, change, asof}. Parse proven against the live file by 05-policy-sources.py's P4 block.
    Raises on a header without `pmms30`, an unparseable date or a blank rate — get_rate() turns
    those into a logged None.

    `change` is the newest release minus the one before it, in PERCENTAGE POINTS, and it is None
    whenever there is no usable prior row. None, never 0.0: a fabricated zero would render as
    "unchanged" — an actual claim about the market — where the truth is "we don't know". Same rule
    market._parse() applies to a lone settled close.

    It is "vs the previous RELEASE", not "vs 7 days ago", and that is the honest framing: PMMS is
    weekly, so the previous row IS last week, but if Freddie Mac ever skips a week the delta is
    still exactly "the move since the last published rate" rather than a broken weekly claim. That
    is why there is no date-gap guard here — there is nothing for one to protect."""
    rows = _rows(raw)
    if len(rows) < 2:                       # header only (or nothing) is not a usable release
        return None
    header = [_cell(h).lower() for h in rows[0]]
    # BY NAME, never by position — an inserted column shifts nothing.
    col = header.index("pmms30")
    last = rows[-1]
    asof = datetime.strptime(_cell(last[0]), "%m/%d/%Y").date().isoformat()
    value = round(float(_cell(last[col])), 2)
    # rows[0] is the header, so rows[-2] is only a data row when there are at least 2 of them.
    prior = _rate_at(rows[-2], col) if len(rows) >= 3 else None
    change = round(value - prior, 2) if prior is not None else None
    return {"value": value, "change": change, "asof": asof}


def _fetch():
    """One bounded PMMS request. Split out so scripts/data/retry.py wraps the NETWORK leg only.

    The read-cap ValueError is raised in here on purpose even though it is not a transport failure:
    retry.transient_reason() does not recognise a ValueError, so it is re-raised immediately rather
    than burning the run's retry budget re-downloading a body that is the wrong size."""
    req = urllib.request.Request(
        config.PMMS_CSV_URL, headers={"User-Agent": PMMS_UA, "Accept": "text/csv, */*"})
    # Explicit timeout: a hung source must not eat the job budget (briefing.yml timeout-minutes: 10).
    with urllib.request.urlopen(req, timeout=config.POLICY_TIMEOUT) as r:
        raw = r.read(_READ_CAP + 1)
    if len(raw) > _READ_CAP:
        # A capped read can end mid-row, and a partial row still parses — as a WRONG rate
        # (e.g. "6.6" out of "6.66"). No rate beats a plausible-looking wrong one.
        raise ValueError(f"PMMS CSV exceeded the {_READ_CAP}-byte read cap")
    return raw


def get_rate():
    """Return {"value": 6.66, "change": -0.03, "asof": "2026-07-30"}, or None.

    Never raises: the mortgage tile is one number on the page, and it must not be able to take the
    briefing down with it. Transient transport failures (a 403 from a rate limiter, a timeout, a
    reset) are retried inside a per-run budget first — see scripts/data/retry.py."""
    try:
        parsed = _parse(retry.call("PMMS CSV", _fetch).decode("utf-8", "replace"))
        if parsed is None:
            raise ValueError("PMMS CSV contained no data rows")
        return parsed
    except Exception as e:
        # Log the real reason — a silent None made the FRED outage invisible for days (see market.py).
        print(f"mortgage: PMMS 30-year rate failed: {type(e).__name__}: {e}")
        return None


def with_last_good(live, st, today):
    """Return (rate_or_None, state). Same idea as build_briefing._get_breadth's last-good cache.

    A good fetch is stored as `mortgage_last_good` and returned with stale=False. A failed fetch
    falls back to that stored reading, marked stale=True and still carrying its OWN `asof`, so the
    page and the narration say "as of <release date>" exactly as they do for a live reading. It is
    served only while that release is at most config.MORTGAGE_LAST_GOOD_MAX_DAYS old: PMMS is
    weekly, so a reading older than that is no longer "the rate", it is history.

    The caller keeps data_availability.mortgage tied to the LIVE fetch, not to this return value.
    A stale number on the page must not hide a dead feed from the degraded ping; that is how the
    two failed runs of 2026-11-25 would have gone unnoticed if the fallback had counted as healthy.

    Never raises: a malformed cache entry degrades to None, the pre-fallback behaviour."""
    st = dict(st or {})
    if live is not None:
        st["mortgage_last_good"] = {k: live.get(k) for k in ("value", "change", "asof")}
        return {**live, "stale": False}, st
    try:
        lg = st.get("mortgage_last_good") or {}
        if lg.get("value") is None or not lg.get("asof"):
            return None, st
        age = (date.fromisoformat(today) - date.fromisoformat(lg["asof"])).days
        if 0 <= age <= config.MORTGAGE_LAST_GOOD_MAX_DAYS:
            print(f"mortgage: serving last good PMMS reading {lg['value']}% as of {lg['asof']} "
                  f"({age} days old, stale)")
            return {"value": lg["value"], "change": lg.get("change"), "asof": lg["asof"],
                    "stale": True}, st
        print(f"mortgage: last good PMMS reading is {age} days old (as of {lg['asof']}), past the "
              f"{config.MORTGAGE_LAST_GOOD_MAX_DAYS}-day limit, so no rate is shown")
    except Exception as e:
        print(f"mortgage: last-good fallback skipped: {type(e).__name__}: {e}")
    return None, st
