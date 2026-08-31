"""Current S&P 500 / Nasdaq-100 constituent symbols, scraped fail-closed from Wikipedia.

stdlib-only on purpose (regex over the `constituents` table) — pandas.read_html+lxml would add
two supply-chain dependencies to the push-capable CI job for one table. The parse is guarded the
same way the plan's pandas version was: if the shape drifts and we can't extract a plausible
count (~503), we raise, and the breadth module degrades to its last-good cache / unavailable —
a biased number must never ship silently.

The parse CONTRACT (table anchor, row regex, plausible bounds) is exported rather than inlined so
04-external-boundary-smoke.py can assert the SHIPPING parse against today's Wikipedia. 04 fetches
with its own hardcoded URL on purpose — an assumption test asserts the assumption, not whatever
config happens to say — but it must not carry a second COPY of the parse: until 2026-08-31 it used
pandas.read_html, which (a) is not installed in CI, so the test could not run there at all, and
(b) is far more tolerant than this regex, so a cell-shape drift that breaks production would have
passed. One parser, two callers.
"""
import re
import urllib.request

from .. import config

# First cell is a LINKED ticker for the S&P table (verified: 503/503) and a PLAIN-TEXT ticker for
# the Nasdaq-100 table (verified: 101). That difference is exactly the kind of drift the regex is
# sensitive to and a tolerant HTML-table reader is not.
SP500_PARSE = {"row_pattern": r'<tr[^>]*>\s*<td[^>]*>\s*<a[^>]*>([A-Z][A-Z0-9.\-]{0,6})</a>',
               "lo": 450, "hi": 520, "what": "sp500"}
NDX100_PARSE = {"row_pattern": r'<tr[^>]*>\s*<td[^>]*>([A-Z][A-Z0-9.\-]{0,6})\s*<',
                "lo": 90, "hi": 110, "what": "ndx100"}


def fetch_page(url):
    """Read a Wikipedia constituents article. Separate from the parse so a test can supply its own URL."""
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_constituents(html, row_pattern, lo, hi, what):
    """Extract unique tickers from the `constituents` table, or raise — never return a partial list."""
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    if not m:
        raise ValueError(f"{what}: constituents table not found (Wikipedia layout drift)")
    unique = list(dict.fromkeys(re.findall(row_pattern, m.group(0))))
    if not lo <= len(unique) <= hi:
        raise ValueError(f"{what}: implausible constituent count {len(unique)}")
    return unique


def sp500_symbols():
    """Current S&P 500 members (~503)."""
    return parse_constituents(fetch_page(config.SP500_WIKI_URL), **SP500_PARSE)


def nasdaq100_symbols():
    """Current Nasdaq-100 members (~101)."""
    return parse_constituents(fetch_page(config.NDX100_WIKI_URL), **NDX100_PARSE)
