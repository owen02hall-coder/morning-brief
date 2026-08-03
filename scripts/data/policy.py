"""Fetch + normalize government policy candidates: Federal Register rules + signed Utah bills.

Contract (the caller is build_briefing.run(), whose main() turns any unhandled exception into a
high-priority "briefing FAILED" push — so nothing here may propagate):

    get_policy(st, today) -> ({"candidates": [...], "available": bool}, new_state)

Both sources are normalized to ONE candidate shape so the prefilter, the sort, the dedupe and the
model prompt only ever know about one thing:

    {id, url, title, abstract, status, effective_date, published, source}

Per-source isolation, mirroring news.py's per-feed isolation, but the two legs are NOT symmetric:

- Federal Register is the backbone and runs every day. A failed fetch **or a zero-result response**
  sets available=False. Zero results over a 45-day, 6-agency window is not a quiet day, it is a
  broken query — the Nasdaq-100 class, where a healthy 200 hid dead data for 22 days (fixed
  0ecff51). So _federal_candidates() RAISES on zero and get_policy() catches it.
- Utah is seasonal (the general session runs Jan-Mar) and optional. Any Utah failure is logged and
  leaves `available` UNCHANGED — a dark legislature must never mark the section unavailable.

Two hard bounds, both about wall time inside briefing.yml's `timeout-minutes: 10` (a cancelled job
ships no briefing at all):
- Every request uses config.POLICY_TIMEOUT and reads at most _MAX_BYTES.
- The Utah harvest does NO detail fetches. It queues stubs; detail pages are fetched lazily at
  release time, at most config.MAX_POLICY_ITEMS per run. Harvesting 491 bills eagerly would be
  ~491 sequential requests.

Bounds on content: abstracts are truncated to _ABSTRACT_CHARS (an enrolled bill is thousands of
words, and an unbounded source text makes summarize's invented-figure guard vacuous), and the
candidate list is capped at config.MAX_POLICY_CANDIDATES.

The Utah bill "detail page" is NOT where the bill text lives. /~2026/bills/static/HB0068.html is a
JavaScript shell: /js/rexBill.js calls loadBillJSON() and paints #docheader / #billbox from
/data/{session}/{number}.json, so the served HTML carries those containers EMPTY and its first
~1,800 stripped characters are the site's global navigation. Stripping that page whole gave the
model half a kilobyte of nav chrome and zero bill text, which also made the invented-figure guard
reject every figure a Utah item carried (the guard compares against the same string). _fetch_bill_
detail() therefore reads the JSON the page itself reads — see _utah_json_text().

None-safety is load-bearing, not defensive style. `effective_on` is legitimately null on proposed
rules and Utah rows carry no publication date, and `None < "2026-08-03"` raises TypeError in
Python 3 — which would take the whole briefing down. Utah candidates therefore stamp
`published = today` (never None) and the sort key is `(c.get("published") or "")`.

This module writes no state itself: it returns a new state dict. state.record_policy() remains the
only writer of policy_seen / policy_active / policy_today; the Utah queue and session stamp are
threaded through here because only the harvest knows what it found.
"""
import json
import re
import urllib.request
from datetime import date, timedelta
from urllib.parse import urljoin

from .. import config

# le.utah.gov is fronted by a filter that is unfriendly to non-browser agents, and the project UA is
# unprobed there; 07-utah-bill-detail.py proved the passed-bills list AND bill detail pages answer
# 200 under EXACTLY this string. Kept module-local (not in config.py) following market.py's YAHOO_UA
# precedent: a per-source quirk belongs next to the code that has the quirk. 07 pins the same
# constant and exists to catch the two drifting apart.
POLICY_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_MAX_BYTES = 2_000_000      # 07 measured real bill pages well under this; a bigger body is not a bill
_ABSTRACT_CHARS = 2000      # bounded source text — see the module docstring

# The bill-summary JSON the bill page itself renders from (rexBill.js: "/data/"+sessionID+"/"+
# billNumber+".json"). The three fields below are the legislature's OWN plain-language summary of
# what the bill does — exactly the material the model needs and the only place it exists in text
# form. Measured across 52 signed bills from 2025GS + 2026GS: 123-4,233 characters, and every one
# of them reads like a bill ("This bill: enacts... amends... repeals...").
_UTAH_BILL_JSON_URL = config.UTAH_BASE_URL + "/data/{session}/{number}.json"
_UTAH_JSON_FIELDS = ("generalProvisions", "highlightedProvisions", "moniesAppropriated")
_UTAH_JSON_MIN_CHARS = 80   # the shortest real summary measured was 123; below this the endpoint
                            # answered but carried no provisions, so prefer the HTML fallback

# Utah ids are "{session}:{number}" (_utah_id); the URL carries the same pair as /~YYYY/.../NNNN.html
# and is the fallback when an id ever arrives in another shape.
_UTAH_KEY_RE = re.compile(r"^(\d{4}[A-Za-z0-9]*)[:](([HS]B)\d{4})$")
_UTAH_URL_RE = re.compile(r"/~(\d{4})/.*?/([HS]B\d{4})\.html?$", re.I)

# HTML fallback slicing. <main id="main-content"> is where le.utah.gov puts the page's own content;
# the nav lives in <header>. Both are tried in order and both degrade to the whole document, so a
# markup change costs text quality, never an exception.
_MAIN_RE = re.compile(r"(?is)<main\b[^>]*>(.*?)</main\s*>")
_HEADER_END_RE = re.compile(r"(?is)</header\s*>")

# The passed-bills row shape: an anchor whose text is the bill number, then nbsp-separated
# title / sponsor / dates / status code. Proven against 495/495 live rows (05, 07, 08).
_ROW_RE = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>\s*([HS]B\d{4})[^<]*</a>(.{0,300}?)(?=<a\s|</tr>|$)',
    re.S | re.I)


def _get(url, ua):
    """One bounded request. Every network call in this module goes through here."""
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=config.POLICY_TIMEOUT) as r:
        return r.read(_MAX_BYTES)


# --- the keyword prefilter ---------------------------------------------------------------------

def _kw_pattern(kw):
    """Word-boundary + inflection, but ONLY where a boundary can exist.

    \\b alone already kills the rent/"current" false positive. The non-obvious part: a trailing \\b
    after a NON-word character can never match, because \\b requires a word/non-word transition. For
    "401(k)" that \\b would sit between ')' and ' ' — two non-word chars — so the naive
    `\\b + escape(kw) + (?:s|es|ing|ed)?\\b` makes that keyword permanently dead, and appending the
    inflection group to it is meaningless too. Same story at the front for a keyword starting with a
    non-word char. The class recurs for any future keyword ending in ')', '%' or '.'.
    Pinned by 08-prefilter-recall.py's B1, which goes red if this regresses."""
    pat = re.escape(kw)
    if kw[:1].isalnum():
        pat = r"\b" + pat
    if kw[-1:].isalnum():
        pat = pat + r"(?:s|es|ing|ed)?\b"
    return pat


_COMPILED = [(kw, re.compile(_kw_pattern(kw))) for kw in config.LIFE_PROFILE_KEYWORDS]


def _matches_profile(c):
    """Return the matched keywords for a candidate (empty list == filtered out).

    ONE matcher for both sources. Utah rows run it at harvest with abstract="" (the title is all the
    harvest has before the detail fetch — 08's R2 proves 4/4 known-relevant Utah titles survive on
    title alone), and everything runs it again once the abstract is filled in."""
    blob = f"{c.get('title') or ''} {c.get('abstract') or ''}".lower()
    return [kw for kw, rx in _COMPILED if rx.search(blob)]


# --- normalization: ONE candidate shape ---------------------------------------------------------

def _normalize_fr(d):
    return {
        "id": d["document_number"],
        "url": d["html_url"],
        "title": d.get("title") or "",
        "abstract": (d.get("abstract") or "")[:_ABSTRACT_CHARS],
        "status": "Final rule" if d.get("type") == "Rule" else "Proposed",
        # LEGITIMATELY None on proposed rules. Every downstream comparison must survive that.
        "effective_date": d.get("effective_on"),
        "published": d.get("publication_date"),
        "source": "Federal Register",
    }


def _utah_id(session, number):
    return f"{session}:{number}"


def _utah_url(href):
    """Utah row hrefs are RELATIVE (/~2026/bills/static/HB0001.html). Un-joined, summarize's host
    allowlist drops 100% of Utah items while every other gate stays green (07's A1)."""
    return urljoin(config.UTAH_BASE_URL, href or "")


def _normalize_utah(row, session, detail_text, today):
    """`row` is either a freshly parsed list row ({number, title, href}) or a queued stub
    ({id, url, title}); the stub already carries the resolved id/url, so both paths produce an
    identical candidate and only one function knows the Utah candidate shape."""
    return {
        "id": row.get("id") or _utah_id(session, row.get("number") or ""),
        "url": row.get("url") or _utah_url(row.get("href")),
        "title": row.get("title") or "",
        "abstract": (detail_text or "")[:_ABSTRACT_CHARS],
        "status": "Signed in Utah",
        "effective_date": None,          # not published on the passed-bills row
        # NEVER None. The candidate sort key is a date string; a None here raises TypeError and
        # takes the entire briefing run down through main()'s crash handler.
        "published": today,
        "source": "Utah Legislature",
    }


# --- Federal Register ---------------------------------------------------------------------------

def _fr_url(agencies, since, per_page):
    """Copied from 05-policy-sources.py, which proves this exact shape against the live API."""
    parts = [f"per_page={per_page}", "order=newest",
             f"conditions[publication_date][gte]={since}",
             "conditions[type][]=RULE", "conditions[type][]=PRORULE"]
    parts += [f"conditions[agencies][]={a}" for a in agencies]
    parts += [f"fields[]={f}" for f in config.FR_FIELDS]
    return config.FR_API + "?" + "&".join(parts)


def _federal_candidates():
    """One request covering all six agencies. RAISES on zero results — see the module docstring."""
    since = (date.today() - timedelta(days=config.FR_WINDOW_DAYS)).isoformat()
    data = json.loads(_get(_fr_url(config.FR_AGENCIES, since, config.FR_PER_PAGE),
                           config.USER_AGENT))
    results = data.get("results") or []
    if not results:
        raise ValueError(
            f"Federal Register returned 0 results for {len(config.FR_AGENCIES)} agencies since "
            f"{since} ({config.FR_WINDOW_DAYS}d) — measured volume is ~21 documents, so this is a "
            f"drifted query or a dead endpoint, not a quiet window")
    count = data.get("count") or 0
    if count > len(results):
        # per_page is the API's page cap and it drops the remainder SILENTLY. 05's FR_MAX_EXPECTED
        # is the CI guard; this line is the production one.
        print(f"policy: WARNING Federal Register returned {len(results)} of {count} documents — "
              f"per_page={config.FR_PER_PAGE} truncated the window")
    return [_normalize_fr(d) for d in results]


# --- Utah Legislature ---------------------------------------------------------------------------

def _strip_tags(html):
    """Stdlib only — no new HTML-parsing dependency is permitted in the push-capable CI job (same
    constraint as scripts/data/constituents.py:1-8).

    COMMENTS ARE REMOVED FIRST, and that is not tidiness. The Utah bill page ships a large
    commented-out EXAMPLE status table (real-looking rows dated 12/19/2023 for a different bill);
    `<[^>]+>` alone eats the `<!--` and the `<TD>`s inside it and leaves that fiction in the text as
    if it were this bill's history. Also used on the JSON summary fields, which carry <hr> and
    <ltbullet> markup of their own."""
    txt = re.sub(r"(?s)<!--.*?-->", " ", html)
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = (txt.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
              .replace("&quot;", '"'))
    return re.sub(r"\s+", " ", txt).strip()


def _parse_rows(html):
    rows = []
    for href, num, tail in _ROW_RE.findall(html):
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", tail).replace("&nbsp;", "|")).strip()
        parts = [p.strip() for p in txt.split("|") if p.strip()]
        title = parts[0] if parts else ""
        if title:
            rows.append({"number": num, "title": title, "href": href,
                         # only GSIGN bills were signed by the governor, i.e. BECAME LAW
                         "signed": "GSIGN" in " ".join(parts[1:])})
    return rows


def _session_chain(session):
    """[session, the prior year's session]. Utah's general session runs Jan-Mar, so for most of the
    year the current session is complete — but a January run would find it empty. Falling back
    keeps the annual harvest from burning its gate on an empty session for the whole year (ported
    from 05-policy-sources.py's Utah loop)."""
    try:
        year = int(str(session)[:4])
    except ValueError:
        return [session]
    return [session, f"{year - 1}GS"]


def _session_for(today):
    """The general session the run's date belongs to, e.g. '2026-08-03' -> '2026GS'."""
    try:
        return f"{int(str(today)[:4])}GS"
    except ValueError:
        return f"{date.today().year}GS"


def _harvest_utah(session):
    """Harvest signed-bill STUBS for a session. Returns (session_used, stubs) or None.

    None means "do not stamp anything as harvested" — the caller must leave the gate open so a
    January run, a half-loaded page or a changed markup retries tomorrow instead of marking the
    session done for a year.

    Stubs are {id, url, title} only. NO detail fetches happen here: up to 491 sequential requests
    would threaten the 10-minute job budget. The title-only prefilter runs here too, because the
    queue drains at MAX_POLICY_ITEMS/day — an unfiltered 491-bill queue would take ~164 days to
    drain and turn selection into a lottery (08's V1 measures the admitted share at 3.5%).
    """
    for candidate in _session_chain(session):
        try:
            html = _get(config.UTAH_PASSED_URL.format(session=candidate),
                        POLICY_UA).decode("utf-8", "replace")
        except Exception as e:
            print(f"policy: Utah passed-bills unreachable for {candidate}: "
                  f"{type(e).__name__}: {e}")
            continue
        signed = [r for r in _parse_rows(html) if r["signed"]]
        if len(signed) < config.UTAH_MIN_SIGNED:
            print(f"policy: Utah {candidate} yielded {len(signed)} signed bills "
                  f"(< {config.UTAH_MIN_SIGNED}) — not stamping it as harvested")
            continue
        stubs = [{"id": _utah_id(candidate, r["number"]),
                  "url": _utah_url(r["href"]),
                  "title": r["title"]}
                 for r in signed if _matches_profile({"title": r["title"], "abstract": ""})]
        print(f"policy: Utah {candidate} harvest: {len(signed)} signed, "
              f"{len(stubs)} pass the prefilter")
        return candidate, stubs
    return None


def _utah_bill_key(stub):
    """(session, number) for a stub, or None. Id first ('2026GS:HB0068' — the session string a
    special session would carry verbatim), URL second."""
    m = _UTAH_KEY_RE.match(str(stub.get("id") or ""))
    if m:
        return m.group(1), m.group(2)
    m = _UTAH_URL_RE.search(str(stub.get("url") or ""))
    if m:
        return f"{m.group(1)}GS", m.group(2).upper()
    return None


def _utah_json_text(session, number):
    """The legislature's own summary of what the bill DOES, from the JSON the bill page renders.

    Deliberately provisions only — no bill number and no title are prepended. Both are already
    separate fields on the candidate (and on the prompt's document line), so spending the model's
    500-character text budget on them would buy nothing; more importantly, injecting them would make
    "the text names this bill" true even when this leg returned nothing, which is precisely the kind
    of self-satisfying check that let the nav-chrome defect ship."""
    data = json.loads(_get(_UTAH_BILL_JSON_URL.format(session=session, number=number),
                           POLICY_UA).decode("utf-8", "replace"))
    return _strip_tags(" ".join(str(data.get(f) or "") for f in _UTAH_JSON_FIELDS))


def _bill_page_text(html):
    """The HTML fallback: the page's own content region, never the site navigation.

    Ordered degradation, each step a superset of the next: <main>, else everything after </header>,
    else the whole document. The last step is the pre-fix behaviour and is kept only so a redesigned
    page still yields SOMETHING; 07's model-visible-slice assertion is what makes reaching it loud."""
    m = _MAIN_RE.search(html)
    if m:
        return _strip_tags(m.group(1))
    m = _HEADER_END_RE.search(html)
    if m:
        return _strip_tags(html[m.end():])
    return _strip_tags(html)


def _fetch_bill_detail(stub):
    """Return ONE bill's source text. Lazy by design: called only for the <=MAX_POLICY_ITEMS stubs
    released from the queue on this run, never during harvest.

    The bill JSON is the primary source (the HTML page has no bill text in it at all — see the
    module docstring). The HTML page is the fallback, sliced to its content region: it yields the
    bill number and the real title and no navigation, which is thin but honest. Falling back is
    printed, because a Utah item summarised from that much text is a degraded item, not a normal one.
    """
    key = _utah_bill_key(stub)
    if key:
        try:
            text = _utah_json_text(*key)
            if len(text) >= _UTAH_JSON_MIN_CHARS:
                return text
            print(f"policy: Utah bill JSON for {stub.get('id')} carried only {len(text)} chars of "
                  f"provisions (< {_UTAH_JSON_MIN_CHARS}) — falling back to the page")
        except Exception as e:
            print(f"policy: Utah bill JSON unavailable for {stub.get('id')}: "
                  f"{type(e).__name__}: {e} — falling back to the page")
    else:
        print(f"policy: could not derive a session/number for {stub.get('id')} "
              f"({stub.get('url')}) — falling back to the page")
    return _bill_page_text(_get(stub["url"], POLICY_UA).decode("utf-8", "replace"))


def _maybe_harvest_utah(st, today):
    """Annual. Returns a new state dict (possibly unchanged)."""
    target = _session_for(today)
    if st.get("policy_utah_session") == target:
        return st
    harvested = _harvest_utah(target)
    if not harvested:
        return st
    session_used, stubs = harvested
    queue = list(st.get("policy_utah_queue") or [])
    # Don't re-queue what is already queued or already reported. Matters on the fallback path: a
    # January run harvests LAST year's session again, which was drained months ago.
    known = {s.get("id") for s in queue} | set(st.get("policy_seen") or {})
    queue += [s for s in stubs if s["id"] not in known]
    # Stamping session_used (not target) is what reopens the gate tomorrow when the fallback fired:
    # session_used != target, so the next run tries the real current session again.
    return {**st, "policy_utah_queue": queue, "policy_utah_session": session_used}


def _release_utah(st, today):
    """Pop <=MAX_POLICY_ITEMS stubs and fetch detail for THOSE ONLY. Returns (candidates, state).

    The pop happens BEFORE the model call and state.save() persists the shortened queue on EVERY
    run, so the caller MUST hand unreported releases back via requeue_utah() — see there."""
    queue = list(st.get("policy_utah_queue") or [])
    released = []
    while queue and len(released) < config.MAX_POLICY_ITEMS:
        stub = queue.pop(0)
        try:
            text = _fetch_bill_detail(stub)
        except Exception as e:
            # Dropped, not re-queued: a permanently dead URL at the head of the queue would eat a
            # fetch slot every single day and block the backfill behind it forever.
            print(f"policy: Utah detail fetch failed for {stub.get('id')} "
                  f"({stub.get('url')}): {type(e).__name__}: {e} — dropping from the queue")
            continue
        released.append(_normalize_utah(stub, None, text, today))
    return released, {**st, "policy_utah_queue": queue}


def requeue_utah(st, candidates):
    """Put released-but-UNREPORTED Utah candidates back at the FRONT of the queue. New state, pure.

    _release_utah() pops before the model runs, and run() calls state.save() on every run — so
    without this, one Gemini outage DELETES those bills. Nothing re-queues them either: the
    seen-write is (correctly) gated on ok=True, and `policy_utah_session` is stamped, so the annual
    harvest will not re-find them until the next general session in March. Observed live: the queue
    went 17 -> 14 while policy_seen stayed federal-only, i.e. 3 signed bills lost for ~7 months.

    FRONT, in their original order, so the same stubs are the next ones released tomorrow instead of
    going to the back of a multi-month backfill.

    Deliberately NOT the inverse of the whole pop — only what the caller actually SENT comes back:
    - a stub whose DETAIL FETCH failed never reaches the caller and stays dropped, on purpose (a
      permanently dead URL at the head would eat one of the three daily slots forever);
    - a released stub that the abstract-level prefilter or the MAX_POLICY_CANDIDATES cap dropped was
      genuinely evaluated, and re-releasing it every day would block the backfill behind it.

    Never raises: it runs on a failure path, in a section that must not be able to crash the run.
    """
    try:
        queue = list(st.get("policy_utah_queue") or [])
        queued = {s.get("id") for s in queue}
        back = []
        for c in candidates or []:
            cid = c.get("id")
            if c.get("source") != "Utah Legislature" or not cid or cid in queued:
                continue
            queued.add(cid)
            # The stub shape {id, url, title} round-trips losslessly: _normalize_utah() copies all
            # three straight off the stub, and only `abstract` (re-fetched next run) is derived.
            back.append({"id": cid, "url": c.get("url"), "title": c.get("title") or ""})
        if not back:
            return st
        print(f"policy: returning {len(back)} unreported Utah bill(s) to the front of the queue "
              f"({', '.join(s['id'] for s in back)})")
        return {**st, "policy_utah_queue": back + queue}
    except Exception as e:
        print(f"policy: Utah re-queue failed: {type(e).__name__}: {e}")
        return st


# --- the public entry point ----------------------------------------------------------------------

def get_policy(st, today):
    """Return ({"candidates": [...], "available": bool}, new_state). NEVER raises.

    `available` reflects the FEDERAL leg only: it is the daily backbone, and it is what the degraded
    ping and data_availability.policy are about. Utah is seasonal — its failure is logged and leaves
    `available` alone."""
    st = dict(st or {})
    available = True
    candidates = []

    try:
        candidates += _federal_candidates()
    except Exception as e:
        print(f"policy: federal leg failed: {type(e).__name__}: {e}")
        available = False

    try:
        st = _maybe_harvest_utah(st, today)
    except Exception as e:
        print(f"policy: Utah harvest failed (availability unaffected): {type(e).__name__}: {e}")

    try:
        released, st = _release_utah(st, today)
        candidates += released
    except Exception as e:
        print(f"policy: Utah release failed (availability unaffected): {type(e).__name__}: {e}")

    try:
        seen = st.get("policy_seen") or {}
        fresh = [c for c in candidates if c["id"] not in seen and _matches_profile(c)]
        # None-safe sort key: `published` is a date string on both sources, but a normalizer bug or
        # a missing Federal Register field must degrade the ORDER, never raise.
        fresh.sort(key=lambda c: (c.get("published") or ""), reverse=True)
        fresh = fresh[: config.MAX_POLICY_CANDIDATES]
    except Exception as e:
        # Last-resort guard: this leg cannot reach main()'s "briefing FAILED" handler.
        print(f"policy: candidate assembly failed: {type(e).__name__}: {e}")
        return {"candidates": [], "available": False}, st

    print(f"policy: {len(candidates)} fetched, {len(fresh)} new candidates "
          f"(federal available={available})")
    return {"candidates": fresh, "available": available}, st
