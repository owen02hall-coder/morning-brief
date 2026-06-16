#!/usr/bin/env python3
"""
ASSUMPTION 4 (boundary smoke): the no-key external read-surfaces are alive and shaped as expected —
(A1) the configured RSS feeds parse and enough items land within the news window; (A2) the Wikipedia
constituent tables still parse to ~500 / ~100 via a header-matched symbol column; (A3) the symbol
normalization (Wikipedia 'BRK.B'/'BF.B' form) produces a stable, expected output.

Runnable NOW (no API key). The live "do class-share symbols actually RESOLVE on Twelve Data" check
lives in 01 (A3), which has the key. Read-only.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
NEGATIVE CONTROL (controllable): set FRESH_HOURS_OVERRIDE=0 to force A1's freshness check red, and
EXPECT_SP500_OVERRIDE to an absurd count to force A2 red.
"""
import os, sys, json, io, urllib.request
from datetime import datetime, timezone, timedelta
from calendar import timegm

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr); sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "briefing-assumption-test/1.0"}
FRESH_HOURS = int(os.environ.get("FRESH_HOURS_OVERRIDE", "72"))
MIN_RECENT_ITEMS = 8
EXPECT_SP500 = int(os.environ.get("EXPECT_SP500_OVERRIDE", "500"))

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
    try:
        import pandas as pd
    except ImportError:
        print("INFRA: pandas/lxml required — pip install pandas lxml", file=sys.stderr); sys.exit(3)

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

    # A2 — Wikipedia tables parse to plausible counts via a header-matched column
    counts = {}
    for key, page, expect in (("sp500", "List_of_S%26P_500_companies", EXPECT_SP500),
                              ("ndx", "Nasdaq-100", 100)):
        try:
            html = urllib.request.urlopen(
                urllib.request.Request("https://en.wikipedia.org/wiki/" + page, headers=UA), timeout=25).read().decode()
            found = None
            for tbl in pd.read_html(io.StringIO(html)):
                col = next((c for c in tbl.columns if str(c).lower() in ("symbol", "ticker")), None)
                if col is not None and len(tbl) >= expect * 0.8:
                    found = [str(s).strip().upper() for s in tbl[col].tolist()]; break
            counts[key] = len(found) if found else 0
            if not found or not (expect * 0.8 <= len(found) <= expect * 1.2):
                failures.append(f"A2 {key}: got {counts[key]} symbols, expected ~{expect} (fail-closed would trigger)")
        except Exception as e:
            failures.append(f"A2 {key}: Wikipedia parse failed: {str(e)[:160]}")

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
