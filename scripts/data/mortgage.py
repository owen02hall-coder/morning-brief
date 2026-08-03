"""Freddie Mac PMMS 30-year fixed mortgage rate — the one part of the policy feature with content
52 weeks a year, and the single most house-buying-relevant number available.

Freddie Mac publishes the Primary Mortgage Market Survey as a plain history CSV (2,889 rows as of
2026-07-30). The header is `date,pmms30,pmms30p,pmms15,...` and rows are oldest-first with `M/D/YYYY`
dates, so the LAST row is the current release. The 30-year rate is read by COLUMN NAME, never by
position, so an inserted column shifts nothing.

get_rate() returns {value, asof} or None:
- value : the 30-year fixed rate as a float (e.g. 6.66)
- asof  : the release date that rate belongs to (YYYY-MM-DD)

The survey is released WEEKLY (Thursday), so on most mornings the newest row is several days old —
that is this source's normal state, not staleness. There is deliberately NO freshness guard here: one
would fire every Monday and turn a healthy feed into a false alarm. A genuinely stalled feed, a moved
column or a changed date format is caught instead by the weekly assumption gate
(`scripts/briefing-assumptions/05-policy-sources.py` P4, which bounds the row age at 14 days).

Any failure degrades to None rather than raising, so the briefing still ships.
"""
import urllib.request
from datetime import datetime

from .. import config

# freddiemac.com answers this path for a browser-like User-Agent; the project UA is unprobed there,
# and 05-policy-sources.py proved P4 against the live file using exactly this shape. Module-local on
# purpose, following market.YAHOO_UA: it is a property of THIS host's bot filtering, not a project
# identity, so it must not migrate into config.py where it would read as the global UA.
PMMS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# The history file is ~150 KB and grows ~4 KB/year, so this is ~25x headroom. It exists only to bound
# a pathological response; hitting it is treated as an error, never as data (see get_rate).
_READ_CAP = 4_000_000


def _parse(raw):
    """Pull the newest 30-year rate out of a PMMS history CSV -> {value, asof}.

    Parse proven against the live file by 05-policy-sources.py's P4 block. Raises on a header without
    `pmms30`, an unparseable date or a blank rate — get_rate() turns those into a logged None."""
    rows = [r for r in raw.splitlines() if r.strip()]
    if len(rows) < 2:                       # header only (or nothing) is not a usable release
        return None
    header = [h.strip() for h in rows[0].split(",")]
    last = rows[-1].split(",")
    asof = datetime.strptime(last[0].strip(), "%m/%d/%Y").date().isoformat()
    value = round(float(last[header.index("pmms30")].strip()), 2)
    return {"value": value, "asof": asof}


def get_rate():
    """Return {"value": 6.66, "asof": "2026-07-30"} for the 30-year fixed rate, or None.

    Never raises: the mortgage tile is one number on the page, and it must not be able to take the
    briefing down with it."""
    req = urllib.request.Request(
        config.PMMS_CSV_URL, headers={"User-Agent": PMMS_UA, "Accept": "text/csv, */*"})
    try:
        # Explicit timeout: a hung source must not eat the job budget (briefing.yml timeout-minutes: 10).
        with urllib.request.urlopen(req, timeout=config.POLICY_TIMEOUT) as r:
            raw = r.read(_READ_CAP + 1)
        if len(raw) > _READ_CAP:
            # A capped read can end mid-row, and a partial row still parses — as a WRONG rate
            # (e.g. "6.6" out of "6.66"). No rate beats a plausible-looking wrong one.
            raise ValueError(f"PMMS CSV exceeded the {_READ_CAP}-byte read cap")
        parsed = _parse(raw.decode("utf-8", "replace"))
        if parsed is None:
            raise ValueError("PMMS CSV contained no data rows")
        return parsed
    except Exception as e:
        # Log the real reason — a silent None made the FRED outage invisible for days (see market.py).
        print(f"mortgage: PMMS 30-year rate failed: {type(e).__name__}: {e}")
        return None
