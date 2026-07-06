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


def sp500_symbols():
    """Return the current constituent symbol list (~503). Raises on any shape drift."""
    req = urllib.request.Request(config.SP500_WIKI_URL,
                                 headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r'id="constituents".*?</table>', html, re.S)
    if not m:
        raise ValueError("constituents table not found (Wikipedia layout drift)")
    # Each data row's first cell is a link whose text is the ticker (verified 2026-07-05: 503/503).
    syms = re.findall(r'<tr[^>]*>\s*<td[^>]*>\s*<a[^>]*>([A-Z][A-Z0-9.\-]{0,6})</a>', m.group(0))
    unique = list(dict.fromkeys(syms))
    if not 450 <= len(unique) <= 520:
        raise ValueError(f"implausible constituent count {len(unique)} (expected ~503)")
    return unique
