#!/usr/bin/env python3
"""
ASSUMPTION 5 (policy sources): the load-bearing external surfaces for the planned
"policy that affects me" section are alive, keyless, and shaped as the design assumes —

(P1) the Federal Register API answers a MULTI-AGENCY, type-filtered, date-windowed query in one
     request, and every result carries the fields the item format depends on
     (title, html_url, publication_date, type, agencies, abstract, effective_on, document_number);
(P2) every result's html_url is on a federalregister.gov host — the design's ".gov primary source"
     guard is enforceable in code, not just asserted in a prompt;
(P3) the volume that query returns is BOUNDED (a few dozen per 45 days, not thousands), so the
     candidate set fits the model's token budget the way the RSS buckets do;
(P4) Freddie Mac's PMMS history CSV parses and its newest row is FRESH — this is the mortgage-rate
     number a house-buying briefing lives on;
(P5) the Utah Legislature's passed-bills page is scrapable for a completed general session (Utah
     publishes no JSON API — HTML scraping is the only route, so its parseability is load-bearing).

Runnable NOW (no API key). Read-only: nothing is written outside this directory's fingerprint.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.

NEGATIVE CONTROLS (controllable, all verified to actually go red on 2026-08-03):
  FR_SINCE_OVERRIDE=2099-01-01          -> forces P1 red (valid query, zero results)
  PMMS_MAX_AGE_DAYS_OVERRIDE=0          -> forces P4 red (nothing is ever that fresh)
  UTAH_MIN_PASSED_OVERRIDE=99999        -> forces P5 red
  (unset BRIEFING_SMOKE_ALLOW_DEV)      -> REFUSED, exit 2

DISCOVERED PROPERTY (not a control): FR_AGENCY_OVERRIDE=not-an-agency returns HTTP 400, not an
empty result set — so a MISSPELLED agency slug fails LOUDLY (exit 3 INFRA) instead of silently
returning nothing and quietly dropping that agency's coverage. That is the good failure mode: the
silent-coverage-hole risk this test was written to catch does not exist at this boundary, which is
why P1's empty-result control has to be driven by the date window instead.

KNOWN-DEAD — probed 2026-08-03 and deliberately NOT depended on (do not re-add without re-probing):
  Congress.gov API          HTTP 403 without an api.data.gov key (key-gated, not keyless)
  CFPB newsroom feed        HTTP 403 to both bot and browser user-agents
  FHFA / IRS / HUD RSS      HTTP 404 at every documented-looking path
  Utah Tax Commission RSS   200 but ZERO entries (published-but-dead feed)
  propertytax.utah.gov      200 but JS-rendered; static fetch yields no Truth-in-Taxation text
  Utah Housing Corp feed    HTTP 403 / 503
  le.utah.gov bulk "Bill Data"  an iframe wrapper, not a downloadable dataset
CFPB/FHFA/IRS/HUD rulemaking is covered by P1 anyway — the Federal Register carries their rules,
which is exactly why it is the backbone rather than a per-agency feed collection.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "briefing-assumption-test/1.0"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

FR_API = "https://www.federalregister.gov/api/v1/documents.json"
# The agencies whose rulemaking can move a first-time buyer's / married filer's numbers.
# NOTE the deliberate use of `employee-benefits-security-administration` rather than the whole
# `labor-department`: measured 2026-08-03, the parent slug returned 46 documents in 45 days of which
# 26 were Labor — almost entirely OSHA chemical-exposure limits (Benzene, Asbestos, Cadmium, Ethylene
# Oxide...) and Mine Safety rules, none of which can touch this user. Narrowing to EBSA (health plans
# + retirement, the only Labor sub-agency in scope) cut the candidate set 46 -> 21 with ZERO loss of
# relevant items. Filtering noise at the source beats spending model tokens rejecting it.
FR_AGENCIES = [
    "housing-and-urban-development-department",
    "federal-housing-finance-agency",
    "consumer-financial-protection-bureau",
    "internal-revenue-service",
    "employee-benefits-security-administration",
    "education-department",
]
FR_FIELDS = ["title", "html_url", "publication_date", "type", "agencies",
             "abstract", "effective_on", "document_number"]
FR_WINDOW_DAYS = 45
FR_MAX_EXPECTED = 400      # bound: blowing past this means the query shape drifted, and the
                           # candidate set would no longer fit a single model call
PMMS_CSV = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
PMMS_MAX_AGE_DAYS = int(os.environ.get("PMMS_MAX_AGE_DAYS_OVERRIDE", "14"))  # weekly release
UTAH_PASSED = "https://le.utah.gov/asp/passedbills/passedbills.asp?session={session}"
UTAH_MIN_PASSED = int(os.environ.get("UTAH_MIN_PASSED_OVERRIDE", "100"))


def _get(url, headers=UA, cap=2_000_000, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(cap)


def _fr_url(agencies, since, per_page=100):
    parts = [f"per_page={per_page}", "order=newest",
             f"conditions[publication_date][gte]={since}",
             "conditions[type][]=RULE", "conditions[type][]=PRORULE"]
    parts += [f"conditions[agencies][]={a}" for a in agencies]
    parts += [f"fields[]={f}" for f in FR_FIELDS]
    return FR_API + "?" + "&".join(parts)


def main():
    failures = []
    fp = {"checked_at": datetime.now(timezone.utc).isoformat()}

    # --- P1/P2/P3: Federal Register ------------------------------------------------
    agencies = [os.environ["FR_AGENCY_OVERRIDE"]] if os.environ.get("FR_AGENCY_OVERRIDE") else FR_AGENCIES
    since = os.environ.get("FR_SINCE_OVERRIDE") or (date.today() - timedelta(days=FR_WINDOW_DAYS)).isoformat()
    try:
        data = json.loads(_get(_fr_url(agencies, since)))
    except urllib.error.HTTPError as e:
        print(f"INFRA: Federal Register API HTTP {e.code}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"INFRA: Federal Register API unreachable: {e}", file=sys.stderr)
        sys.exit(3)

    count = data.get("count") or 0
    results = data.get("results") or []
    fp["federal_register"] = {"window_days": FR_WINDOW_DAYS, "since": since,
                              "agencies": len(agencies), "count": count,
                              "returned": len(results)}

    if not results:
        failures.append(f"P1 Federal Register returned 0 results for {len(agencies)} agencies since "
                        f"{since} — the agency slugs or query shape drifted")
    else:
        missing = {}
        for r in results:
            for f in FR_FIELDS:
                # effective_on is legitimately null on proposed rules; presence of the KEY is what
                # the item format needs (a null renders as "no effective date yet").
                if f not in r:
                    missing.setdefault(f, 0)
                    missing[f] += 1
        if missing:
            failures.append(f"P1 fields absent from results: {missing} — the three-line item format "
                            f"(what happened / what it means / effective date) depends on these")

        # P2 — the ".gov primary source" guard must be enforceable in code
        bad_hosts = sorted({r.get("html_url", "") for r in results
                            if not str(r.get("html_url", "")).startswith(
                                "https://www.federalregister.gov/")})
        if bad_hosts:
            failures.append(f"P2 {len(bad_hosts)} result URL(s) not on www.federalregister.gov "
                            f"(e.g. {bad_hosts[0][:80]}) — the .gov allowlist guard would reject them")

        typed = sorted({r.get("type") for r in results})
        fp["federal_register"]["types_seen"] = typed
        if not set(typed) <= {"Rule", "Proposed Rule"}:
            failures.append(f"P1 type filter leaked non-rule documents: {typed} — Notices and "
                            f"Presidential Documents would flood the candidate set")

    # P3 — bounded volume
    if count > FR_MAX_EXPECTED:
        failures.append(f"P3 {count} documents in {FR_WINDOW_DAYS} days exceeds the expected bound "
                        f"({FR_MAX_EXPECTED}) — candidate set no longer fits one model call")

    # --- P4: Freddie Mac PMMS mortgage rate ---------------------------------------
    try:
        raw = _get(PMMS_CSV, headers=BROWSER_UA).decode("utf-8", "replace")
        rows = [r for r in raw.splitlines() if r.strip()]
        header = rows[0].split(",")
        last = rows[-1].split(",")
        if "pmms30" not in header:
            failures.append(f"P4 PMMS header lacks 'pmms30': {header[:6]} — the 30-year rate column moved")
        last_date = datetime.strptime(last[0], "%m/%d/%Y").date()
        age = (date.today() - last_date).days
        rate30 = last[header.index("pmms30")] if "pmms30" in header else None
        fp["pmms"] = {"rows": len(rows), "latest_date": last_date.isoformat(),
                      "age_days": age, "pmms30": rate30}
        if age > PMMS_MAX_AGE_DAYS:
            failures.append(f"P4 newest PMMS row is {age} days old ({last_date}) — expected a weekly "
                            f"release within {PMMS_MAX_AGE_DAYS} days; the feed may be stalled")
        if not rate30:
            failures.append("P4 newest PMMS row has no 30-year rate value")
    except Exception as e:
        failures.append(f"P4 PMMS CSV unusable: {type(e).__name__}: {str(e)[:120]}")

    # --- P5: Utah Legislature passed-bills page ------------------------------------
    # Utah's general session runs Jan-Mar, so the CURRENT year's session is complete for most of the
    # year. Early in a year (before that session's bills pass) fall back to the prior year, so this
    # test does not go red simply because the session has not happened yet.
    utah = {}
    for year in (date.today().year, date.today().year - 1):
        session = f"{year}GS"
        try:
            html = _get(UTAH_PASSED.format(session=session), headers=BROWSER_UA).decode("utf-8", "replace")
        except Exception as e:
            utah[session] = f"unreachable: {type(e).__name__}"
            continue
        # The row shape carries everything the item format needs: an anchor whose text is the bill
        # number, followed by nbsp-separated title / sponsor / dates / status code. Parsing the
        # TITLE and the STATUS (not just counting bill numbers) is what is actually load-bearing —
        # relevance scoring reads titles, and only GSIGN bills BECAME LAW.
        rows = re.findall(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*([HS]B\d{4})[^<]*</a>(.{0,300}?)(?=<a\s|</tr>|$)',
            html, re.S | re.I)
        titled, signed = [], 0
        for href, num, tail in rows:
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tail).replace("&nbsp;", "|")).strip()
            parts = [p.strip() for p in txt.split("|") if p.strip()]
            title = parts[0] if parts else ""
            if title:
                titled.append((num, title))
            if "GSIGN" in " ".join(parts[1:]):
                signed += 1
        utah[session] = {"rows": len(rows), "with_title": len(titled), "signed": signed}
        if signed >= UTAH_MIN_PASSED:
            utah["session_used"] = session
            utah["sample_title"] = titled[0][1][:80] if titled else None
            break
    fp["utah_legislature"] = utah
    if "session_used" not in utah:
        failures.append(f"P5 no Utah session yielded >={UTAH_MIN_PASSED} governor-signed bills with "
                        f"parseable titles (saw {utah}) — the passed-bills page moved or its row "
                        f"markup changed; Utah has no JSON API, so this scrape is the only route")
    else:
        used = utah[utah["session_used"]]
        if used["with_title"] < used["rows"]:
            failures.append(f"P5 {used['rows'] - used['with_title']} of {used['rows']} rows yielded no "
                            f"title — relevance scoring reads titles, so a partial parse silently "
                            f"drops bills from consideration")

    # --- verdict -------------------------------------------------------------------
    if failures:
        print("FAIL: 05-policy-sources", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(HERE, "05-policy-sources.fingerprint.json"), "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2)
    used = utah.get(utah.get("session_used"), {})
    print(f"PASS: 05-policy-sources — P1..P5 "
          f"(FR: {fp['federal_register']['count']} rules/{FR_WINDOW_DAYS}d across "
          f"{len(agencies)} agencies; PMMS 30yr={fp.get('pmms', {}).get('pmms30')} "
          f"@{fp.get('pmms', {}).get('latest_date')}; Utah {utah.get('session_used')}: "
          f"{used.get('signed')} signed / {used.get('with_title')} titled)")


if __name__ == "__main__":
    main()
