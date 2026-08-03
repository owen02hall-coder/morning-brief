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

The Federal Register query shape (FR_API / FR_AGENCIES / FR_FIELDS / FR_WINDOW_DAYS / FR_PER_PAGE)
is IMPORTED from scripts/config.py, not copied here: a local copy would let this gate keep proving a
query production no longer sends. FR_MAX_EXPECTED is this test's own bound but is DERIVED from
config.FR_PER_PAGE for the same reason — a second hardcoded number drifts away from the page size it
is supposed to be protecting.

NEGATIVE CONTROLS (controllable, all verified to actually go red on 2026-08-03):
  FR_SINCE_OVERRIDE=2099-01-01          -> forces P1 red (valid query, zero results)
  PMMS_MAX_AGE_DAYS_OVERRIDE=0          -> forces P4 red (nothing is ever that fresh)
  UTAH_MIN_PASSED_OVERRIDE=99999        -> forces P5 red
  (unset BRIEFING_SMOKE_ALLOW_DEV)      -> REFUSED, exit 2

  FR_PER_PAGE_OVERRIDE=5                -> does NOT go red; it forces the API to TRUNCATE and then
     asserts (P3b) that `count` still reports the full total, i.e. count > len(results). That is a
     property, not a failure: production requests per_page=config.FR_PER_PAGE (100) and the API
     drops everything past it SILENTLY, so the only thing standing between growth and quiet
     data-loss is FR_MAX_EXPECTED — which can only detect truncation if `count` counts past the
     page. If `count` ever tracked the page instead, tying FR_MAX_EXPECTED to the page size would be
     a guard that can never fire. Set the override BELOW the live volume
     (~21 documents / 45 days) or the assertion simply does not engage, and the run says so.
     This run does not rewrite the fingerprint — its numbers are deliberately truncated.

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
# The repo root, so `from scripts import config` resolves however this file is invoked: by bare path
# (run-all.sh:22 does `python "${SCRIPT_DIR}/${t}"`) and from data-smoke.yml. `python -m` is not an
# option here — the filenames start with digits and contain hyphens, and this directory has no
# __init__.py — so sys.path is the route.
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from scripts import config  # noqa: E402

UA = {"User-Agent": "briefing-assumption-test/1.0"}
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# The Federal Register query shape is IMPORTED, never copied. A local copy would let production and
# this gate drift apart silently — the test would keep proving a query nothing ships. config carries
# the WHY for each value (agency choice, window, page size); this file proves them against the live
# API.
#
# FR_MAX_EXPECTED is this test's own bound, but DERIVED from config.FR_PER_PAGE, never a second
# hardcoded number. This bound's real job is to go
# red BEFORE production loses data: the API drops everything past per_page SILENTLY, so at 400 (the
# original value) a window that grew to 150 documents would have truncated 50 of them in production
# while this test stayed green — a guard positioned where it could never fire. 80% of the page size
# leaves a margin instead of firing at the exact document that gets dropped, and today's measured
# volume is 21 documents / 45 days, so there is still ~4x headroom before this needs attention.
# P3b (below) is what makes the bound meaningful at all: it proves `count` reports total matches
# rather than the page, so growth past the page size is visible here.
FR_MAX_EXPECTED = int(config.FR_PER_PAGE * 0.8)     # 80 at FR_PER_PAGE=100
# When set, overrides config.FR_PER_PAGE — see the pagination control in the docstring.
FR_PER_PAGE_OVERRIDE = os.environ.get("FR_PER_PAGE_OVERRIDE")
PMMS_CSV = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
PMMS_MAX_AGE_DAYS = int(os.environ.get("PMMS_MAX_AGE_DAYS_OVERRIDE", "14"))  # weekly release
UTAH_PASSED = "https://le.utah.gov/asp/passedbills/passedbills.asp?session={session}"
UTAH_MIN_PASSED = int(os.environ.get("UTAH_MIN_PASSED_OVERRIDE", "100"))


def _get(url, headers=UA, cap=2_000_000, timeout=25):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(cap)


def _fr_url(agencies, since, per_page):
    parts = [f"per_page={per_page}", "order=newest",
             f"conditions[publication_date][gte]={since}",
             "conditions[type][]=RULE", "conditions[type][]=PRORULE"]
    parts += [f"conditions[agencies][]={a}" for a in agencies]
    parts += [f"fields[]={f}" for f in config.FR_FIELDS]
    return config.FR_API + "?" + "&".join(parts)


def main():
    failures = []
    fp = {"checked_at": datetime.now(timezone.utc).isoformat()}

    # --- P1/P2/P3: Federal Register ------------------------------------------------
    agencies = ([os.environ["FR_AGENCY_OVERRIDE"]] if os.environ.get("FR_AGENCY_OVERRIDE")
                else config.FR_AGENCIES)
    since = (os.environ.get("FR_SINCE_OVERRIDE")
             or (date.today() - timedelta(days=config.FR_WINDOW_DAYS)).isoformat())
    per_page = int(FR_PER_PAGE_OVERRIDE) if FR_PER_PAGE_OVERRIDE else config.FR_PER_PAGE
    try:
        data = json.loads(_get(_fr_url(agencies, since, per_page)))
    except urllib.error.HTTPError as e:
        print(f"INFRA: Federal Register API HTTP {e.code}", file=sys.stderr)
        sys.exit(3)
    except Exception as e:
        print(f"INFRA: Federal Register API unreachable: {e}", file=sys.stderr)
        sys.exit(3)

    count = data.get("count") or 0
    results = data.get("results") or []
    fp["federal_register"] = {"window_days": config.FR_WINDOW_DAYS, "since": since,
                              "agencies": len(agencies), "count": count,
                              "per_page": per_page, "returned": len(results),
                              "truncated": len(results) < count}

    if not results:
        failures.append(f"P1 Federal Register returned 0 results for {len(agencies)} agencies since "
                        f"{since} — the agency slugs or query shape drifted")
    else:
        missing = {}
        for r in results:
            for f in config.FR_FIELDS:
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
        failures.append(f"P3 {count} documents in {config.FR_WINDOW_DAYS} days exceeds the expected "
                        f"bound ({FR_MAX_EXPECTED} = 80% of config.FR_PER_PAGE={config.FR_PER_PAGE}) "
                        f"— production requests ONE page and the API drops the remainder silently, "
                        f"so this is the warning before real data loss: raise FR_PER_PAGE, narrow "
                        f"FR_WINDOW_DAYS or paginate")

    # P3b — `count` must report TOTAL matches, independent of the page size we asked for. That single
    # property is what makes FR_MAX_EXPECTED a real truncation guard: production requests
    # per_page=config.FR_PER_PAGE and would silently drop every document past it, and the bound can
    # only see that if `count` keeps counting past the page. If `count` ever tracked the PAGE, the
    # guard would be vacuous and lowering it (plan Task 9) would prove nothing. Only asserted when
    # FR_PER_PAGE_OVERRIDE forces truncation, because at the real page size nothing truncates.
    if FR_PER_PAGE_OVERRIDE and results:
        if len(results) > per_page:
            failures.append(f"P3 API returned {len(results)} results for per_page={per_page} — the "
                            f"page-size parameter is being ignored, so FR_PER_PAGE is not a bound")
        elif len(results) == per_page and count <= len(results):
            failures.append(f"P3 page filled at per_page={per_page} but count={count} does not "
                            f"exceed it — `count` reports the PAGE, not the total, so pagination "
                            f"truncation is invisible and FR_MAX_EXPECTED can never catch it")
        elif len(results) < per_page:
            print(f"NOTE: per_page={per_page} did not truncate ({count} documents in the window) — "
                  f"the pagination assertion did not fire. Use a value below the live volume.",
                  file=sys.stderr)

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

    # A per_page-override run PASSES (unlike every other control here, which goes red), so it would
    # otherwise overwrite the committed fingerprint with a deliberately truncated `returned` count
    # and misrepresent the real volume. Skip the write instead.
    if FR_PER_PAGE_OVERRIDE:
        print("NOTE: FR_PER_PAGE_OVERRIDE set — fingerprint NOT rewritten", file=sys.stderr)
    else:
        with open(os.path.join(HERE, "05-policy-sources.fingerprint.json"), "w", encoding="utf-8") as fh:
            json.dump(fp, fh, indent=2)
    used = utah.get(utah.get("session_used"), {})
    print(f"PASS: 05-policy-sources — P1..P5 "
          f"(FR: {fp['federal_register']['count']} rules/{config.FR_WINDOW_DAYS}d across "
          f"{len(agencies)} agencies; PMMS 30yr={fp.get('pmms', {}).get('pmms30')} "
          f"@{fp.get('pmms', {}).get('latest_date')}; Utah {utah.get('session_used')}: "
          f"{used.get('signed')} signed / {used.get('with_title')} titled)")


if __name__ == "__main__":
    main()
