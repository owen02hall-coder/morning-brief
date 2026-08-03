#!/usr/bin/env python3
"""
ASSUMPTION 8 (prefilter recall + precision): the LIFE_PROFILE keyword prefilter sits UPSTREAM of the
only component this project has actually proven, and nothing gates it.

06-policy-relevance.py feeds the model all 24 candidates unfiltered and shows it picks well. The
planned pipeline instead sends the model only what `_matches_profile` survives. A recall hole there
is invisible in production — the section simply looks quiet, which is exactly the state the design
declares "normal". This test is the gate for that stage.

Deliberately NOT recall-only. The keyword list was authored by reading these very documents, so
"do the known-relevant items match?" is near-tautological: `KEYWORDS = ["a"]` would pass it. Teeth
come from precision and volume:

  (R1) RECALL/federal — the two documents the live model actually selected (pinned by
       document_number so the fixture cannot roll out of the 45-day window) both match.
  (R2) RECALL/Utah — four known-relevant signed bills match on TITLE ALONE, which is all the
       harvest has before the detail fetch.
  (P1) PRECISION — a must-NOT-match set: a real Utah appropriations bill and the three decoy
       abstracts 06 uses (benzene, mine ventilation, blacksmith shops). A prefilter that admits
       these is not filtering.
  (V1) VOLUME — the prefilter admits no more than MAX_VOLUME_PCT of the LIVE signed Utah rows.
       Load-bearing: with output truncated at MAX_POLICY_ITEMS, an over-broad prefilter turns
       selection into a lottery rather than a filter.
  (B1) BOUNDARY — the word-boundary + inflection matcher behaves: 'rent' must NOT match
       'current'/'parental' (the r1 false-positive class), 'mortgage' MUST match 'mortgages', and
       '401(k)' MUST match '401(k) contribution limit'.

B1's last case is a REAL BUG this test exists to pin: the naive
`r"\\b" + re.escape(kw) + r"(?:s|es|ing|ed)?\\b"` can NEVER match a keyword ending in a
non-word character. For '401(k)' the trailing \\b sits between ')' and ' ' — two non-word chars,
so no boundary exists. The fix (`_kw_pattern` below) appends the inflection group and the trailing
boundary only when the keyword ends alphanumerically.

Runnable NOW (no API key). Read-only. Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.

NEGATIVE CONTROLS (controllable, both verified red at authoring time 2026-08-03):
  PREFILTER_KEYWORDS_OVERRIDE=zzz
      -> R1 + R2 red: neither pinned federal document nor any Utah title survives.
  PREFILTER_KEYWORDS_OVERRIDE="amendment,income tax,property tax,housing,401(k),direct loan,health plan"
      -> P1 + V1 red: 'amendment' admits the appropriations bill AND 383/491 (78.0%) of all signed
         Utah bills, well over the 18% ceiling.
      (A bare 'a' also goes red, but on RECALL, not precision — '\\ba\\b' matches almost nothing.
       Recording the distinction because a control that fails for the wrong reason proves the
       wrong thing.)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "briefing-assumption-test/1.0"}
BROWSER_UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}

# The proposed production list. Once scripts/config.py defines LIFE_PROFILE_KEYWORDS this test
# imports it instead, so the gate follows what actually ships rather than a frozen copy.
PROPOSED_KEYWORDS = [
    "mortgage", "loan limit", "down payment", "closing cost", "escrow", "appraisal",
    "house", "housing", "home", "homebuyer", "first-time buyer", "rent", "rental", "landlord",
    "property tax", "properties", "zoning", "adu",
    "income tax", "tax bracket", "standard deduction", "deduction", "married filing jointly",
    "withholding", "tax credit",
    "student loan", "repayment", "borrower", "pell", "direct loan",
    "health insurance", "health plan", "premium", "open enrollment", "hsa", "marketplace",
    "retirement", "401(k)", "ira", "contribution limit",
]

try:                                                  # prefer the shipped list once it exists
    sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
    from scripts import config as _cfg                # noqa: E402
    KEYWORDS = list(getattr(_cfg, "LIFE_PROFILE_KEYWORDS", PROPOSED_KEYWORDS))
    SOURCE = "config.LIFE_PROFILE_KEYWORDS" if hasattr(_cfg, "LIFE_PROFILE_KEYWORDS") else "proposed"
except Exception:
    KEYWORDS, SOURCE = PROPOSED_KEYWORDS, "proposed"

if os.environ.get("PREFILTER_KEYWORDS_OVERRIDE"):
    KEYWORDS = [k.strip() for k in os.environ["PREFILTER_KEYWORDS_OVERRIDE"].split(",")]
    SOURCE = "override"

MAX_VOLUME_PCT = float(os.environ.get("PREFILTER_MAX_VOLUME_PCT", "18"))

# Pinned 2026-08-03 from CI run 30840533176 — the two documents the live model selected.
PINNED_FR = {
    "2026-13286": "Accountability in Higher Education … William D. Ford Direct Loan (student loans)",
    "2026-14917": "Electronic Disclosure by Group Health Plans Under ERISA (employer health plan)",
}

UTAH_RELEVANT_TITLES = [
    "Income Tax Rate Amendments",
    "Property Tax Exemption Process Amendments",
    "Moderate Income Housing Infrastructure Amendments",
    "Housing and Community Development Amendments",
]

MUST_NOT_MATCH = [
    ("utah-appropriations", "Public Education Base Budget Amendments", ""),
    ("osha-benzene", "Benzene",
     "OSHA proposes to update the permissible exposure limit for benzene in workplace air for "
     "general industry, maritime, and construction."),
    ("msha-ventilation", "Ventilation Plan Approval Criteria",
     "The Mine Safety and Health Administration proposes criteria for approving ventilation plans "
     "in underground coal mines."),
    ("msha-blacksmith", "Improving and Eliminating Regulations; Blacksmith Shops",
     "MSHA removes obsolete requirements governing blacksmith shops at mines."),
]


def _kw_pattern(kw):
    """Word-boundary + inflection, but ONLY where a boundary can exist.

    A trailing \\b after a non-word character (the ')' in '401(k)') can never match, because \\b
    requires a word/non-word transition. Same for a leading \\b before a non-word char. Appending
    the inflection group to such a keyword is meaningless too."""
    pat = re.escape(kw)
    if kw[:1].isalnum():
        pat = r"\b" + pat
    if kw[-1:].isalnum():
        pat = pat + r"(?:s|es|ing|ed)?\b"
    return pat


_COMPILED = None


def matches(title, abstract=""):
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = [(kw, re.compile(_kw_pattern(kw))) for kw in KEYWORDS]
    blob = f"{title} {abstract}".lower()
    return [kw for kw, rx in _COMPILED if rx.search(blob)]


def _get(url, headers=UA, timeout=25, cap=2_000_000):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout).read(cap)


def main():
    failures = []
    fp = {"checked_at": datetime.now(timezone.utc).isoformat(),
          "keyword_source": SOURCE, "keyword_count": len(KEYWORDS)}

    # --- R1: the two documents the live model selected -------------------------------------
    recall_fr = {}
    for docnum, label in PINNED_FR.items():
        url = (f"https://www.federalregister.gov/api/v1/documents/{docnum}.json"
               "?fields[]=title&fields[]=abstract&fields[]=document_number")
        try:
            d = json.loads(_get(url))
        except urllib.error.HTTPError as e:
            print(f"INFRA: pinned document {docnum} HTTP {e.code}", file=sys.stderr)
            sys.exit(3)
        except Exception as e:
            print(f"INFRA: pinned document {docnum} unreachable: {e}", file=sys.stderr)
            sys.exit(3)
        hits = matches(d.get("title", ""), d.get("abstract") or "")
        recall_fr[docnum] = hits
        if not hits:
            failures.append(f"R1 {docnum} ({label}) does NOT survive the prefilter — the model "
                            f"selected this document; the prefilter would never let it see it")
    fp["recall_federal"] = recall_fr

    # --- R2: Utah, title-only (all the harvest has pre-detail) ------------------------------
    recall_utah = {}
    for title in UTAH_RELEVANT_TITLES:
        hits = matches(title, "")
        recall_utah[title] = hits
        if not hits:
            failures.append(f"R2 Utah title {title!r} does not survive the prefilter on title alone")
    fp["recall_utah"] = recall_utah

    # --- P1: precision ----------------------------------------------------------------------
    precision = {}
    for name, title, abstract in MUST_NOT_MATCH:
        hits = matches(title, abstract)
        precision[name] = hits
        if hits:
            failures.append(f"P1 {name} MATCHED on {hits} — {title!r} must never reach the model")
    fp["precision"] = precision

    # --- V1: volume against the live Utah list ----------------------------------------------
    rows = []
    for year in (date.today().year, date.today().year - 1):
        try:
            html = _get(f"https://le.utah.gov/asp/passedbills/passedbills.asp?session={year}GS",
                        headers=BROWSER_UA).decode("utf-8", "replace")
        except Exception:
            continue
        found = re.findall(
            r'<a[^>]+href=["\'][^"\']+["\'][^>]*>\s*([HS]B\d{4})[^<]*</a>(.{0,300}?)(?=<a\s|</tr>|$)',
            html, re.S | re.I)
        parsed = []
        for _num, tail in found:
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tail).replace("&nbsp;", "|")).strip()
            parts = [p.strip() for p in txt.split("|") if p.strip()]
            if parts and "GSIGN" in " ".join(parts[1:]):
                parsed.append(parts[0])
        if len(parsed) >= 100:
            rows = parsed
            fp["utah_session"] = f"{year}GS"
            break
    if not rows:
        print("INFRA: could not load a Utah signed-bill list for the volume check", file=sys.stderr)
        sys.exit(3)

    passed = [t for t in rows if matches(t, "")]
    pct = 100.0 * len(passed) / len(rows)
    fp["volume"] = {"signed_rows": len(rows), "passed": len(passed), "pct": round(pct, 1),
                    "ceiling_pct": MAX_VOLUME_PCT}
    if pct > MAX_VOLUME_PCT:
        failures.append(f"V1 prefilter admits {len(passed)}/{len(rows)} ({pct:.1f}%) of signed Utah "
                        f"bills, over the {MAX_VOLUME_PCT}% ceiling — with output capped at "
                        f"MAX_POLICY_ITEMS this makes selection a lottery, not a filter")

    # --- B1: boundary + inflection behaviour -------------------------------------------------
    cases = [
        ("rent-in-current", "Current Expense Amendments", "", "rent", False),
        ("rent-in-parental", "Parental Rights Amendments", "", "rent", False),
        ("mortgage-plural", "Mortgages and Lending Amendments", "", "mortgage", True),
        ("401k-paren", "Retirement Plan Changes", "raises the 401(k) contribution limit", "401(k)", True),
        ("housing-word", "Housing and Community Development Amendments", "", "housing", True),
    ]
    boundary = {}
    for name, title, abstract, kw, want in cases:
        if kw not in KEYWORDS:
            continue                                   # override runs skip these
        got = bool(re.compile(_kw_pattern(kw)).search(f"{title} {abstract}".lower()))
        boundary[name] = got
        if got != want:
            failures.append(f"B1 {name}: keyword {kw!r} match={got}, expected {want} — "
                            f"pattern was {_kw_pattern(kw)!r}")
    fp["boundary"] = boundary

    if failures:
        print("FAIL: 08-prefilter-recall", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(HERE, "08-prefilter-recall.fingerprint.json"), "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2)
    print(f"PASS: 08-prefilter-recall — R1,R2,P1,V1,B1 (keywords from {SOURCE}, n={len(KEYWORDS)}; "
          f"both pinned FR docs retained; 4/4 Utah titles; 0/{len(MUST_NOT_MATCH)} decoys admitted; "
          f"volume {len(passed)}/{len(rows)} = {pct:.1f}% of ceiling {MAX_VOLUME_PCT}%)")


if __name__ == "__main__":
    main()
