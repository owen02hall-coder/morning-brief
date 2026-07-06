"""Current S&P 500 constituent symbols, scraped fail-closed from Wikipedia.

stdlib-only on purpose (regex over the `constituents` table) — pandas.read_html+lxml would add
two supply-chain dependencies to the push-capable CI job for one table. The parse is guarded the
same way the plan's pandas version was: if the shape drifts and we can't extract a plausible
count (~503), we raise, and the breadth module degrades to its last-good cache / unavailable —
a biased number must never ship silently.
"""
import re
import urllib.request

from .. import config


def _constituents(url, row_pattern, lo, hi, what):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    if not m:
        raise ValueError(f"{what}: constituents table not found (Wikipedia layout drift)")
    unique = list(dict.fromkeys(re.findall(row_pattern, m.group(0))))
    if not lo <= len(unique) <= hi:
        raise ValueError(f"{what}: implausible constituent count {len(unique)}")
    return unique


def sp500_symbols():
    """Current S&P 500 members (~503). First cell is a LINKED ticker (verified: 503/503)."""
    return _constituents(config.SP500_WIKI_URL,
                         r'<tr[^>]*>\s*<td[^>]*>\s*<a[^>]*>([A-Z][A-Z0-9.\-]{0,6})</a>',
                         450, 520, "sp500")


def nasdaq100_symbols():
    """Current Nasdaq-100 members (~101). First cell is a PLAIN-TEXT ticker (verified: 101)."""
    return _constituents(config.NDX100_WIKI_URL,
                         r'<tr[^>]*>\s*<td[^>]*>([A-Z][A-Z0-9.\-]{0,6})\s*<',
                         90, 110, "ndx100")
