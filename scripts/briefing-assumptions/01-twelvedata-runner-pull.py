#!/usr/bin/env python3
"""
ASSUMPTION 1 (the whole ballgame): a ~600-symbol daily market-data pull succeeds from a
GitHub Actions RUNNER IP via Twelve Data, within the free credit budget, and the index symbols
resolve (or a documented fallback engages).

WHY IT IS LOAD-BEARING: yfinance was dropped precisely because Yahoo IP-blocks GitHub Actions
runners. Twelve Data is the replacement. A LOCAL pass does NOT prove the runner case — run this as
a `workflow_dispatch` job inside Actions to truly close the risk. (It still runs locally to prove
the API contract + credit cost.)

Read-only against Twelve Data. Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
NEGATIVE CONTROL (synthetic-injection): a bogus symbol 'ZZZZ_NOPE' is injected into the universe;
A1's missing-symbol detector MUST count it as missing — if it doesn't, the >=95% check is blind.
"""
import os, sys, json, io, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr); sys.exit(2)

API_KEY = os.environ.get("TWELVEDATA_API_KEY")
if not API_KEY:
    print("INFRA: TWELVEDATA_API_KEY not set — cannot prove the data spine (create a free key)", file=sys.stderr)
    sys.exit(3)

BASE = "https://api.twelvedata.com"
HERE = os.path.dirname(os.path.abspath(__file__))
RAN_IN_CI = os.environ.get("GITHUB_ACTIONS") == "true"
CREDIT_BUDGET = 650          # plan's ~604/day + headroom; NOT the 800 ceiling
INDEX_CANDIDATES = {         # try several forms; record which resolve
    "sp500": ["GSPC", "SPX", "INX"], "nasdaq100": ["NDX", "IXIC"],
    "vix": ["VIX"], "ten_year": ["TNX"],
}

def _get(path, **params):
    params["apikey"] = API_KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())

def api_credits_used():
    try:
        u = _get("api_usage")
        return u.get("current_usage")
    except Exception:
        return None

def wiki_symbols(page, expect):
    """Minimal universe fetch; if it fails the data-spine test can't run (INFRA)."""
    try:
        import pandas as pd
    except ImportError:
        print("INFRA: pandas/lxml required to load the constituent universe", file=sys.stderr); sys.exit(3)
    req = urllib.request.Request("https://en.wikipedia.org/wiki/" + page,
                                 headers={"User-Agent": "briefing-assumption-test/1.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    for tbl in pd.read_html(io.StringIO(html)):
        col = next((c for c in tbl.columns if str(c).lower() in ("symbol", "ticker")), None)
        if col is not None and len(tbl) >= expect * 0.8:
            return [str(s).strip().upper() for s in tbl[col].tolist()]
    raise RuntimeError(f"no symbol column found on {page}")

def normalize(sym):
    # Wikipedia 'BRK.B' -> Twelve Data convention. Twelve Data uses the dot form; try as-is.
    return sym.replace("​", "").strip()

def batch_quote(symbols):
    """Return set of symbols that returned a usable close. Chunked to respect per-request limits."""
    ok = set()
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i+100]
        try:
            data = _get("quote", symbol=",".join(chunk))
        except urllib.error.URLError as e:
            print(f"INFRA: network error talking to Twelve Data: {e}", file=sys.stderr); sys.exit(3)
        # single-symbol responses are a bare object; multi are keyed by symbol
        items = data.values() if (len(chunk) > 1 and isinstance(data, dict) and "symbol" not in data) else [data]
        for it in items:
            if isinstance(it, dict) and it.get("close") not in (None, "", "0"):
                ok.add(str(it.get("symbol", "")).upper())
        time.sleep(1)   # be gentle on rate limits
    return ok

def main():
    failures = []
    try:
        sp = wiki_symbols("List_of_S%26P_500_companies", 500)
        nd = wiki_symbols("Nasdaq-100", 100)
    except Exception as e:
        print(f"INFRA: could not load constituent universe: {e}", file=sys.stderr); sys.exit(3)

    universe = sorted({normalize(s) for s in sp + nd})
    BOGUS = "ZZZZ_NOPE"
    probe = universe + [BOGUS]                              # negative-control injection
    klass = [s for s in ("BRK.B", "BF.B", "BRK-B", "BF-B") if s in {x for x in (sp+nd)}]

    before = api_credits_used()
    returned = batch_quote(probe)
    after = api_credits_used()
    credits = (after - before) if (before is not None and after is not None) else None

    # A1 — >=95% of the real universe returns a recent close
    got = len(returned & set(universe))
    pct = 100 * got / len(universe) if universe else 0
    if pct < 95: failures.append(f"A1 only {pct:.1f}% of {len(universe)} constituents returned a close (need >=95%)")
    # NEGATIVE CONTROL: the bogus symbol must NOT be in returned (detector works)
    if BOGUS in returned: failures.append("NEG-CONTROL bogus symbol reported as valid — missing-detection is blind")

    # A2 — index symbols resolve (record which); 10Y may need the FRED fallback
    resolved = {}
    for name, cands in INDEX_CANDIDATES.items():
        hit = next((c for c in cands if c in batch_quote([c])), None)
        resolved[name] = hit
        if hit is None and name != "ten_year":
            failures.append(f"A2 no Twelve Data symbol resolved for {name} (tried {cands})")
    # ten_year absent is tolerated (documented FRED DGS10 fallback) but recorded.

    # A3 — class-share tickers resolve under the chosen normalization (if any exist in the list)
    if klass:
        kres = batch_quote([normalize(k) for k in klass])
        if not (kres & {normalize(k) for k in klass}):
            failures.append(f"A3 class-share symbols {klass} did not resolve on Twelve Data — fix normalization")

    # A4 — a daily snapshot stays within the credit budget (headroom, not the 800 ceiling)
    if credits is not None and credits > CREDIT_BUDGET:
        failures.append(f"A4 daily snapshot used {credits} credits (> {CREDIT_BUDGET} budget)")

    fp = {"ran_in_ci": RAN_IN_CI, "constituent_count": len(universe), "pct_returned": round(pct, 1),
          "resolved_index_symbols": resolved, "credits_per_daily_snapshot": credits,
          "credit_budget": CREDIT_BUDGET, "checked_at": datetime.now(timezone.utc).isoformat()}

    if failures:
        print("FAIL: 01-twelvedata-runner-pull", file=sys.stderr)
        for f in failures: print("  -", f, file=sys.stderr)
        if not RAN_IN_CI:
            print("  NOTE: ran LOCALLY — even on PASS this does not prove the runner-IP case; run in CI.", file=sys.stderr)
        sys.exit(1)

    json.dump(fp, open(os.path.join(HERE, "01-twelvedata-runner-pull.fingerprint.json"), "w"), indent=2)
    where = "CI runner" if RAN_IN_CI else "LOCAL (does NOT prove runner-IP — re-run in CI)"
    print(f"PASS: 01-twelvedata-runner-pull — A1,A2,A3,A4 [{where}] "
          f"({pct:.1f}% of {len(universe)}, {credits} credits, indices={resolved})")

if __name__ == "__main__":
    main()
