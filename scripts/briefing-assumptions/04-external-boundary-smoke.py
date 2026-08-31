#!/usr/bin/env python3
"""
ASSUMPTION 4 (boundary smoke): the no-key external read-surfaces are alive and shaped as expected —
(A1) the configured RSS feeds parse and enough items land within the news window; (A2) the Wikipedia
constituent tables still parse to ~500 / ~100 THROUGH THE PRODUCTION PARSER; (A3) the symbol
normalization (Wikipedia 'BRK.B'/'BF.B' form) produces a stable, expected output.

Runnable NOW (no API key) and stdlib-only. A2 used pandas.read_html until 2026-08-31; pandas/lxml
are deliberately absent from requirements.txt (config.py:108 — they are not going into the
push-capable job for one table), so this test exited 3 INFRA on its first scheduled CI run and
could never have run there. It now calls scripts.data.constituents, which is also strictly
stronger: read_html tolerates cell-shape drift that breaks the shipping regex.

The live "do class-share symbols actually RESOLVE on Twelve Data" check lives in 01 (A3), which has
the key. Read-only.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA — and 3 now means only "feedparser is missing", never
"a dependency CI was never going to have".
NEGATIVE CONTROL (controllable): set FRESH_HOURS_OVERRIDE=0 to force A1's freshness check red, and
EXPECT_SP500_OVERRIDE to an absurd count to force A2 red.
"""
import os, sys, json, urllib.request
from datetime import datetime, timezone, timedelta
from calendar import timegm

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr); sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
# The workflow exports PYTHONPATH for this step; run-all.sh does not. Resolve the repo root from
# __file__ so A2 reaches the production parser under both.
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from scripts.data import constituents
UA = {"User-Agent": "briefing-assumption-test/1.0"}
FRESH_HOURS = int(os.environ.get("FRESH_HOURS_OVERRIDE", "72"))
MIN_RECENT_ITEMS = 8
# Negative control: an absurd value collapses A2's plausible-count window onto it, forcing red.
_ov = os.environ.get("EXPECT_SP500_OVERRIDE")
SP500_BOUND_OVERRIDE = int(_ov) if _ov else None

WORLD = {"BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
         "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
         "Guardian World": "https://www.theguardian.com/world/rss",
         "NPR": "https://feeds.npr.org/1004/rss.xml"}
BUSINESS = {"MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
            "CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html"}
TECH = {"Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "MIT Tech Review": "https://www.technologyreview.com/feed/",
        "Hacker News": "https://hnrss.org/frontpage"}
ALL_FEEDS = {**WORLD, **BUSINESS, **TECH}

def main():
    failures = []
    try:
        import feedparser
    except ImportError:
        print("INFRA: feedparser required — pip install feedparser", file=sys.stderr); sys.exit(3)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESH_HOURS)
    alive, recent_total, world_alive = [], 0, 0
    for name, url in ALL_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers=UA)
            raw = urllib.request.urlopen(req, timeout=25).read()
            fp = feedparser.parse(raw)
            if fp.entries:
                alive.append(name)
                if name in WORLD: world_alive += 1
                for e in fp.entries:
                    t = e.get("published_parsed") or e.get("updated_parsed")
                    if t and datetime.fromtimestamp(timegm(t), timezone.utc) >= cutoff:
                        recent_total += 1
        except Exception:
            pass   # per-feed isolation: a dead feed is tolerated, not fatal

    # A1 — enough fresh items + at least one world feed alive
    if recent_total < MIN_RECENT_ITEMS:
        failures.append(f"A1 only {recent_total} items within {FRESH_HOURS}h (need >={MIN_RECENT_ITEMS}) "
                        f"— widen window or swap feeds")
    if world_alive < 1:
        failures.append("A1 no world feed alive — world news 'always ships' promise at risk")

    # A2 — the constituent tables still parse, THROUGH THE CODE THAT SHIPS
    counts = {}
    # These page names deliberately mirror config.SP500_WIKI_URL / config.NDX100_WIKI_URL rather
    # than importing them — an assumption test asserts the assumption, not whatever config happens
    # to say. The cost of that choice showed up on 2026-07-13: Wikipedia moved the Nasdaq-100
    # component table to its own list article, and BOTH copies had to be updated. If you change one,
    # change the other. (The spine step covers the other direction: it drives breadth through the
    # CONFIG urls, so a bad config URL goes red there while this step stays honest about the page.)
    #
    # The PARSE, unlike the URL, is imported and not copied. A second implementation here is what
    # made this test unrunnable in CI and blind to cell-shape drift at the same time; the regex,
    # bounds and table anchor now live only in scripts/data/constituents.py.
    for key, page, spec in (("sp500", "List_of_S%26P_500_companies", constituents.SP500_PARSE),
                            ("ndx", "List_of_NASDAQ-100_companies", constituents.NDX100_PARSE)):
        if key == "sp500" and SP500_BOUND_OVERRIDE is not None:
            spec = {**spec, "lo": SP500_BOUND_OVERRIDE, "hi": SP500_BOUND_OVERRIDE}
        try:
            html = constituents.fetch_page("https://en.wikipedia.org/wiki/" + page)
            counts[key] = len(constituents.parse_constituents(html, **spec))
        except Exception as e:
            counts[key] = 0
            failures.append(f"A2 {key}: {type(e).__name__}: {str(e)[:160]} "
                            f"(this is exactly what fails breadth closed downstream)")

    # A3 — normalization produces the expected stable output (string-level)
    def normalize(s): return s.replace("​", "").strip().upper()
    for raw_sym, exp in (("brk.b", "BRK.B"), ("BF.B ", "BF.B"), ("aapl", "AAPL")):
        if normalize(raw_sym) != exp:
            failures.append(f"A3 normalize({raw_sym!r}) = {normalize(raw_sym)!r}, expected {exp!r}")

    fp_out = {"feeds_alive": alive, "feeds_total": len(ALL_FEEDS), "world_feeds_alive": world_alive,
              "recent_items_within_hours": {"hours": FRESH_HOURS, "count": recent_total},
              "constituent_counts": counts, "checked_at": datetime.now(timezone.utc).isoformat()}

    if failures:
        print("FAIL: 04-external-boundary-smoke", file=sys.stderr)
        for f in failures: print("  -", f, file=sys.stderr)
        sys.exit(1)

    json.dump(fp_out, open(os.path.join(HERE, "04-external-boundary-smoke.fingerprint.json"), "w"), indent=2)
    print(f"PASS: 04-external-boundary-smoke — A1,A2,A3 ({len(alive)}/{len(ALL_FEEDS)} feeds alive, "
          f"{recent_total} fresh items, SP500={counts.get('sp500')}, NDX={counts.get('ndx')})")

if __name__ == "__main__":
    main()
