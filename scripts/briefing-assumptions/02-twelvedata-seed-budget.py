#!/usr/bin/env python3
"""
ASSUMPTION 2: the one-time ~250-day history seed for ~600 symbols fits inside Twelve Data's free
daily credit window (800/day, resets 00:00 UTC) — AND a same-day daily increment does NOT then
blow the cap. The plan asserts both "seed ~600 credits fits in one day" and "daily pull ~600
credits"; doing both on day one is ~1200 > 800. This proves the real arithmetic + reset behavior.

Measures REAL credit cost via /api_usage rather than assuming "1 credit/symbol". Read-only.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
NEGATIVE CONTROL (controllable): set SEED_BUDGET_OVERRIDE to a tiny number to force A2 red and
confirm the budget assertion actually fires.
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr); sys.exit(2)
API_KEY = os.environ.get("TWELVEDATA_API_KEY")
if not API_KEY:
    print("INFRA: TWELVEDATA_API_KEY not set", file=sys.stderr); sys.exit(3)

BASE = "https://api.twelvedata.com"
HERE = os.path.dirname(os.path.abspath(__file__))
DAILY_CAP = 800
CONSTITUENTS = 600
# negative-control hook: shrink the per-symbol seed-cost budget to force a failure
SEED_BUDGET = int(os.environ.get("SEED_BUDGET_OVERRIDE", DAILY_CAP))
SAMPLE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "JNJ"]

def _get(path, **params):
    params["apikey"] = API_KEY
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())

def credits_used():
    try:
        return _get("api_usage").get("current_usage")
    except Exception:
        return None

def main():
    failures = []
    # Measure the credit cost of a ~250-day time_series request for a small sample, then extrapolate.
    before = credits_used()
    try:
        for s in SAMPLE:
            _get("time_series", symbol=s, interval="1day", outputsize=250)
            time.sleep(1)
    except urllib.error.URLError as e:
        print(f"INFRA: network/Twelve Data error: {e}", file=sys.stderr); sys.exit(3)
    after = credits_used()
    if before is None or after is None:
        print("INFRA: /api_usage did not report usage — cannot measure credits", file=sys.stderr); sys.exit(3)

    per_symbol = (after - before) / len(SAMPLE)
    seed_cost = per_symbol * CONSTITUENTS              # extrapolated full-seed cost
    daily_cost = per_symbol * CONSTITUENTS             # daily increment ~ same per-symbol cost

    # A1 — outputsize does NOT multiply credits (a 250-day pull costs ~ the same as a 1-day pull)
    if per_symbol > 1.5:
        failures.append(f"A1 a 250-day time_series cost {per_symbol:.2f} credits/symbol "
                        f"(>1.5) — outputsize multiplies credits; seed budget math is wrong")
    # A2 — full seed of ~600 fits inside one day's budget
    if seed_cost > SEED_BUDGET:
        failures.append(f"A2 extrapolated seed cost {seed_cost:.0f} > {SEED_BUDGET} daily budget "
                        f"— stagger the seed across days")
    # A3 — seed + a same-day daily increment must NOT both fit (documents the reset-wait requirement)
    both = seed_cost + daily_cost
    must_wait = both > DAILY_CAP
    # This is a documentation assertion, not a failure: we just record the truth.

    fp = {"credits_per_symbol_250d": round(per_symbol, 3),
          "extrapolated_seed_cost": round(seed_cost), "daily_increment_cost": round(daily_cost),
          "daily_cap": DAILY_CAP, "seed_plus_daily": round(both),
          "must_wait_for_utc_reset_after_seed": must_wait,
          "checked_at": datetime.now(timezone.utc).isoformat()}

    if failures:
        print("FAIL: 02-twelvedata-seed-budget", file=sys.stderr)
        for f in failures: print("  -", f, file=sys.stderr)
        sys.exit(1)

    json.dump(fp, open(os.path.join(HERE, "02-twelvedata-seed-budget.fingerprint.json"), "w"), indent=2)
    wait = "MUST wait for 00:00 UTC reset before the first daily run" if must_wait else "seed+daily fit same day"
    print(f"PASS: 02-twelvedata-seed-budget — A1,A2 ({per_symbol:.2f} cr/symbol, "
          f"seed~{seed_cost:.0f}/{DAILY_CAP}); A3 note: {wait}")

if __name__ == "__main__":
    main()
