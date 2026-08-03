#!/usr/bin/env python3
"""
ASSUMPTION 7 (Utah scrape contract): the Utah half of the policy section is reachable and carries
real bill text — the leg with three separate mechanisms depending on it and, before this test, zero
executable proof.

Test 05 captures each row's `href` and asserts NOTHING about it. If those hrefs are relative (they
are: `/~2026/bills/static/HB0001.html`), summarize's URL guard drops 100% of Utah items while every
other gate stays green. That is a fully silent dead leg.

Proves, on 3 rows sampled from the LIVE passed-bills page (never a hardcoded bill number, which
would rot the moment that bill moved):
  (A1) urljoin(UTAH_BASE_URL, href) yields scheme https and host EXACTLY le.utah.gov — so the
       host allowlist and the `https://` scheme check both pass;
  (A2) the bill detail page returns 200 under the EXACT user-agent production sends;
  (A3) PRODUCTION'S OWN extractor (policy._fetch_bill_detail) yields >= UTAH_DETAIL_MIN_CHARS;
  (A4) the raw body size and per-fetch wall time sit under stated ceilings — the harvest does up to
       MAX_POLICY_ITEMS detail fetches inside a job with `timeout-minutes: 10`, and a cancelled job
       fires a high-priority "briefing FAILED" push and ships no briefing at all;
  (A5) THE SLICE THAT ACTUALLY REACHES THE MODEL is the bill. See below — this is the assertion
       this file now exists for. Checked immediately after A3, since it is A3's real subject.

WHY A5 EXISTS (a defect this file's earlier A3 was blind to, found 2026-08-03). A3 used to assert
that the bill number and title tokens appeared ANYWHERE in the FULL stripped text, using a LOCAL
copy of the tag-strip. Both halves of that were wrong:
  - the bill page's first ~1,800 stripped characters are site navigation, and only the first
    summarize.POLICY_PROMPT_TEXT_CHARS characters ever reach the model — so a check against the full
    4,700-character string passed while the model received nothing but chrome. Every Utah item then
    got a useless summary AND had any figure it carried rejected as invented, because the
    invented-figure guard compares against that same string. The Utah leg produced nothing, silently;
  - a LOCAL copy of the extraction proves the copy, not the shipped code.
A5 therefore imports production and asserts on the exact bytes of the prompt: it builds the
candidate with policy._normalize_utah and reads the `text` field back out of
summarize._policy_docs_block. Two properties, chosen because both survive Utah rewording the page:
fail-CLOSED, the slice must read like a bill (BILL_LANGUAGE — 52/52 signed bills across two sessions
matched); and fail-loud, the slice must contain NO navigation marker (CHROME_MARKERS — the exact
fingerprint of the defect). Title tokens are recorded in the fingerprint but NOT asserted: measured
on 20 signed bills, 3 summarise themselves without reusing a title word, so a hard check there would
be a flaky gate, and a flaky gate gets ignored.

Runnable NOW (no API key — importing scripts.summarize does not construct a client). Read-only:
fetches public pages, writes only this directory's fingerprint.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.

NEGATIVE CONTROLS (controllable, both verified to actually go red on 2026-08-03):
  UTAH_DETAIL_MIN_CHARS_OVERRIDE=999999   forces A3 red.
  UTAH_CHROME_CONTROL=true                replaces the extracted text with the PRE-FIX extraction
     (the whole bill page stripped whole) and forces A5 red. This is the regression this file now
     stands in front of: run it after any change to policy._fetch_bill_detail and confirm it is
     still red, or A5 has quietly stopped measuring anything. Does not rewrite the fingerprint.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlparse

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
# The repo root, so `from scripts...` resolves however this file is invoked (see 05's note: these
# filenames start with digits and the directory has no __init__.py, so `python -m` is not an option).
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from scripts import config                                              # noqa: E402
from scripts.data import policy                                         # noqa: E402
from scripts.summarize import POLICY_PROMPT_TEXT_CHARS, _policy_docs_block   # noqa: E402

# IMPORTED, not copied. The whole point of A5 is that this file measures shipped behaviour; a local
# reimplementation of the user-agent, the extractor or the prompt truncation would let this gate keep
# proving something production no longer does — which is exactly how the chrome defect survived.
POLICY_UA = policy.POLICY_UA
UTAH_BASE_URL = config.UTAH_BASE_URL
UTAH_PASSED_URL = config.UTAH_PASSED_URL
UTAH_MIN_SIGNED = config.UTAH_MIN_SIGNED

SAMPLE_SIZE = 3
# 100, not the old 200: the extractor now returns the bill's own summary instead of 4,700 characters
# of page furniture, and the shortest real summary measured across 52 signed bills from 2025GS and
# 2026GS was 123 characters. 200 would have gone red on a short-but-perfectly-good bill.
DETAIL_MIN_CHARS = int(os.environ.get("UTAH_DETAIL_MIN_CHARS_OVERRIDE", "100"))
DETAIL_MAX_BYTES = 2_000_000        # a bill page far larger than this would blow the token budget
DETAIL_MAX_SECONDS = 20.0           # per fetch; config.POLICY_TIMEOUT is 25
TOTAL_MAX_SECONDS = 90.0            # list + 3 pages + 3 bill-JSON fetches; run-all.sh allows 150s
CHROME_CONTROL = os.environ.get("UTAH_CHROME_CONTROL") == "true"

# A5, fail-closed: the model-visible slice must read like a bill. Matched by 52/52 signed bills
# sampled across 2025GS and 2026GS; the legislature's own summaries all open "This bill ...".
BILL_LANGUAGE = re.compile(
    r"\b(this bill|enacts?|amends?|repeals?|appropriat\w*|requires?|modifies|creates?|provides?|"
    r"prohibits?|defines?|establishes?|authorizes?)\b", re.I)
# A5, fail-loud: the fingerprint of the defect. Every one of these is le.utah.gov's global navigation
# and none of them belongs in a bill summary. Kept as a SECOND check, never the only one — a nav
# redesign would silently retire it, which is why BILL_LANGUAGE above is the fail-closed half.
CHROME_MARKERS = ("skip to content", "accessibility", "find legislators", "reading calendars",
                  "seating chart", "conflict of interest forms", "leadership roster")


def _get(url, timeout=25):
    """Local, because A2 and A4 need the status, the byte count and the wall time that
    policy._get() (correctly) does not expose. The user-agent is production's."""
    req = urllib.request.Request(url, headers={"User-Agent": POLICY_UA})
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(DETAIL_MAX_BYTES + 1)
        return r.status, body, time.monotonic() - started


def _model_visible_text(stub, text):
    """The EXACT `text` value the prompt carries for this bill — production's normalizer, then
    production's document block, then read back out of the JSON line the model receives."""
    candidate = policy._normalize_utah(stub, None, text, date.today().isoformat())
    return json.loads(_policy_docs_block([candidate]))["text"]


def _pick_sample(rows):
    """>=1 HB and >=1 SB so a shape difference between the two chambers cannot hide."""
    hb = [r for r in rows if r["number"].startswith("HB")]
    sb = [r for r in rows if r["number"].startswith("SB")]
    picked = []
    if hb:
        picked.append(hb[len(hb) // 2])
    if sb:
        picked.append(sb[len(sb) // 2])
    for r in rows:
        if len(picked) >= SAMPLE_SIZE:
            break
        if r not in picked:
            picked.append(r)
    return picked[:SAMPLE_SIZE]


def main():
    failures = []
    fp = {"checked_at": datetime.now(timezone.utc).isoformat(), "ua": POLICY_UA}
    t0 = time.monotonic()

    # --- fetch the passed-bills list, current session then prior (session runs Jan-Mar) ----------
    rows, session_used = [], None
    for year in (date.today().year, date.today().year - 1):
        session = f"{year}GS"
        try:
            status, body, _ = _get(UTAH_PASSED_URL.format(session=session))
        except urllib.error.HTTPError as e:
            print(f"INFRA: passed-bills HTTP {e.code} for {session}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"INFRA: passed-bills unreachable for {session}: {e}", file=sys.stderr)
            continue
        parsed = [r for r in policy._parse_rows(body.decode("utf-8", "replace")) if r["signed"]]
        if len(parsed) >= UTAH_MIN_SIGNED:
            rows, session_used = parsed, session
            break
    if not rows:
        print("INFRA: no Utah session yielded a usable signed-bill list — run 05 first",
              file=sys.stderr)
        sys.exit(3)

    fp["session"] = session_used
    fp["signed_rows"] = len(rows)

    sample = _pick_sample(rows)
    fp["sampled"] = [r["number"] for r in sample]
    if len(sample) < SAMPLE_SIZE:
        failures.append(f"A1 could only sample {len(sample)} rows (wanted {SAMPLE_SIZE})")

    details = []
    for r in sample:
        # --- A1: relative href must resolve to an absolute, allowlisted URL --------------------
        resolved = urljoin(UTAH_BASE_URL, r["href"])
        parts = urlparse(resolved)
        if parts.scheme != "https":
            failures.append(f"A1 {r['number']}: scheme is {parts.scheme!r}, not https "
                            f"(href={r['href']!r}) — the URL guard would drop this item")
        if parts.hostname != "le.utah.gov":
            failures.append(f"A1 {r['number']}: host is {parts.hostname!r}, not le.utah.gov "
                            f"— the host allowlist would drop this item")

        # --- A2: the detail page answers under the PRODUCTION user-agent ----------------------
        try:
            status, body, elapsed = _get(resolved, timeout=int(DETAIL_MAX_SECONDS) + 5)
        except urllib.error.HTTPError as e:
            failures.append(f"A2 {r['number']}: detail page HTTP {e.code} at {resolved}")
            continue
        except Exception as e:
            failures.append(f"A2 {r['number']}: detail fetch failed: {type(e).__name__} {str(e)[:80]}")
            continue
        if status != 200:
            failures.append(f"A2 {r['number']}: detail page status {status}")

        # --- A3: PRODUCTION's extractor returns usable text ------------------------------------
        stub = {"id": f"{session_used}:{r['number']}", "url": resolved, "title": r["title"]}
        started = time.monotonic()
        try:
            text = policy._fetch_bill_detail(stub)
        except Exception as e:                                  # noqa: BLE001
            failures.append(f"A3 {r['number']}: policy._fetch_bill_detail raised "
                            f"{type(e).__name__}: {str(e)[:80]} — production would drop this bill")
            continue
        extract_s = time.monotonic() - started
        if CHROME_CONTROL:
            # The PRE-FIX extraction: the whole page stripped whole. Forces A5 red on purpose.
            text = policy._strip_tags(body.decode("utf-8", "replace"))
        if len(text) < DETAIL_MIN_CHARS:
            failures.append(f"A3 {r['number']}: extracted text is {len(text)} chars "
                            f"(need >={DETAIL_MIN_CHARS}) — nothing for the model to summarize")

        # --- A5: THE SLICE THAT REACHES THE MODEL IS THE BILL ----------------------------------
        # Not the full text: only the first POLICY_PROMPT_TEXT_CHARS characters are ever sent, and
        # asserting against the full string is precisely what let 1,800 characters of navigation
        # ship as a bill "abstract". See the module docstring.
        slice_ = _model_visible_text(stub, text)
        head = slice_.lower()
        if not BILL_LANGUAGE.search(slice_):
            failures.append(
                f"A5 {r['number']}: the first {POLICY_PROMPT_TEXT_CHARS} characters that reach the "
                f"model contain no bill language ({BILL_LANGUAGE.pattern[:60]}...) — only that "
                f"ceiling is ever sent, so whatever policy._fetch_bill_detail put first is ALL the "
                f"model sees. Got: {slice_[:120]!r}")
        chrome = [m for m in CHROME_MARKERS if m in head]
        if chrome:
            failures.append(
                f"A5 {r['number']}: site navigation ({chrome}) is inside the first "
                f"{POLICY_PROMPT_TEXT_CHARS} characters that reach the model — the extractor is "
                f"returning page furniture, which also makes the invented-figure guard compare the "
                f"model's figures against chrome and drop every Utah item carrying a number")
        # Recorded, deliberately NOT asserted — see the docstring (3 of 20 bills summarise
        # themselves without reusing a title word; a flaky gate is a gate nobody trusts).
        tokens = re.findall(r"[a-z]{4,}", r["title"].lower())
        title_hits = [t for t in tokens if t in head]

        # --- A4: bounded size and time ---------------------------------------------------------
        if len(body) > DETAIL_MAX_BYTES:
            failures.append(f"A4 {r['number']}: body {len(body)}B exceeds {DETAIL_MAX_BYTES}B")
        for label, secs in (("page fetch", elapsed), ("production extract", extract_s)):
            if secs > DETAIL_MAX_SECONDS:
                failures.append(f"A4 {r['number']}: {label} took {secs:.1f}s "
                                f"(ceiling {DETAIL_MAX_SECONDS}s)")
        details.append({"number": r["number"], "url": resolved, "bytes": len(body),
                        "text_chars": len(text), "elapsed_s": round(elapsed, 2),
                        "extract_s": round(extract_s, 2),
                        "prompt_chars": len(slice_),
                        "title_tokens_in_slice": f"{len(title_hits)}/{len(tokens)}",
                        # The committed fingerprint shows a HUMAN what the model is being fed. Had
                        # this line existed, the chrome defect would have been visible in review.
                        "model_sees": slice_[:160]})

    fp["details"] = details
    fp["prompt_text_ceiling"] = POLICY_PROMPT_TEXT_CHARS
    total = time.monotonic() - t0
    fp["total_elapsed_s"] = round(total, 2)
    if total > TOTAL_MAX_SECONDS:
        failures.append(f"A4 total wall time {total:.1f}s exceeds {TOTAL_MAX_SECONDS}s — the "
                        f"harvest would threaten the 10-minute job budget")

    if failures:
        print("FAIL: 07-utah-bill-detail", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(HERE, "07-utah-bill-detail.fingerprint.json"), "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2)
    print(f"PASS: 07-utah-bill-detail — A1..A5 ({session_used}: {len(rows)} signed; sampled "
          f"{', '.join(d['number'] for d in details)}; "
          f"text {min(d['text_chars'] for d in details)}-{max(d['text_chars'] for d in details)} chars, "
          f"of which the model sees the first {POLICY_PROMPT_TEXT_CHARS}; "
          f"total {total:.1f}s)")


if __name__ == "__main__":
    main()
