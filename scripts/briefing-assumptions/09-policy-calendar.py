#!/usr/bin/env python3
"""
ASSUMPTION 9 (the policy calendar cannot go stale): `config.POLICY_CALENDAR` is the one part of the
policy section that is HARDCODED. Every other leg is fetched, and a fetch that breaks is loud — a
hardcoded list that rots is silent, and it rots into the worst possible failure mode: a confident
date on screen that is wrong or already in the past, under a heading that says "What's coming".

The calendar was cut from an earlier revision of this feature for exactly that reason — "no shape,
no source, no staleness story". This file IS the staleness story. It is a runnable machine, not a
paragraph, because the failure it guards is silent by construction: nothing in production compares a
calendar date to reality, so a stale entry renders as happily as a good one.

WHY A NEW FILE AND NOT MORE ASSERTIONS IN 08. 08 is a NETWORK test — it fetches federalregister.gov
and le.utah.gov and exits 3 (INFRA) when they are unreachable. Bolting an offline, pure-logic gate
onto it would make a Utah outage HIDE a calendar regression, which is the same "one dead leg masks
the others" shape that data-smoke.yml's per-step `if: always()` exists to prevent. 09 needs no key,
no network and no dependency, so it can run anywhere, in milliseconds, on every change.

  (C1) FRESHNESS — every entry's next occurrence is a date that is NOT IN THE PAST, from each of
       several reference dates including December 31 and January 1 (the year-boundary case: a
       November entry seen in December must resolve to NEXT November), and is within 366 days
       (which is what makes an impossible month/day such as February 29 loud here rather than an
       entry that silently never appears).
  (C2) NO FIXED YEARS — no entry carries a year in any form: not as a key, not inside a label. An
       entry with a year is a dated fact, and a dated fact is the thing that goes stale.
  (C3) SHAPE — every entry has a valid month/day and a non-empty label, note and https URL.
  (C4) ORDER — the horizon filter returns entries in ascending date order. "What's coming" read out
       of order is worse than not shown.
  (C5) HONESTY — every label reads as ANTICIPATORY: it contains the word "expected" and contains no
       4-digit year and no precise "Month DD". Exact dates move year to year, and stating one the
       source has not announced is the calendar's version of the model authoring a figure. Precise
       dates belong in `note`, which is sourcing and context, not a claim about this year.
  (C6) HORIZON — the shipped horizon leaves the forward-looking block empty on a meaningful share of
       days. Load-bearing: "Policy that affects you" renders ONLY when non-empty, and a horizon wide
       enough to keep an entry on screen every day would silently convert it into an always-on
       section. Measured against the real calendar over a full year.
  (C7) ANNOUNCED LINES EXPIRE. `config.POLICY_ANNOUNCED` replaces a calendar line once its source
       has published (2026-11-25: the page still said the loan limit was "expected" a day after
       FHFA announced it). Those lines carry real years and figures, so each needs its own
       staleness story: a primary-source https url, a `key` that matches a calendar entry, and an
       `expires` no more than config.POLICY_ANNOUNCED_MAX_DAYS (about 120) after `announced`.
       Also proves the replacement through PRODUCTION code: on the announcement day the line is
       shown with its `announced` marker, and the day after expiry it is gone.

Runnable NOW (no API key, no network, no dependencies). Read-only. Exit: 0 PASS / 1 FAIL / 2 REFUSED.

NEGATIVE CONTROLS (`POLICY_CALENDAR_CONTROL=<mode>`, each driving PRODUCTION code red — all four
verified red at authoring time, 2026-08-03; long-expiry added 2026-11-25):
  no-rollforward  -> C1 red. Replaces production `policy._next_occurrence` with the naive same-year
                     version (`date(today.year, m, d)`), i.e. exactly the December->January bug the
                     roll-forward exists to prevent.
  fixed-year      -> C2 red. Appends an entry carrying a `year` key and a year in its label.
  blank-note      -> C3 red. Appends an entry whose note is empty.
  long-expiry     -> C7 red. Appends an announced entry whose expiry is a year out and whose url is
                     plain http, i.e. a dated fact that would outlive the year it describes.
  no-sort         -> C4 red. Neutralises production's `policy._calendar_sort_key` to a constant;
                     Python's sort is stable, so the output falls back to config order. This control
                     can only engage where config order differs from date order — the test says so
                     on stderr if it cannot, because a control that cannot fail proves nothing.
"""
import json
import os
import re
import sys
from datetime import date, timedelta

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from scripts import config                       # noqa: E402
from scripts.data import policy                  # noqa: E402

CONTROL = os.environ.get("POLICY_CALENDAR_CONTROL", "")

# Reference dates C1/C3 resolve from. Deliberately includes both sides of the year boundary, the
# leap day, and the day after each entry's own anchor is not needed — the month sweep below covers
# every entry's "just passed" case.
REFERENCE_DATES = [date.today(), date(2026, 12, 31), date(2027, 1, 1), date(2028, 2, 29)]
REFERENCE_DATES += [date(2027, m, d) for m in range(1, 13) for d in (1, 15, 28)]

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# "November 25", "Nov. 25", "April 15" — a precise day, which no label may claim.
PRECISE_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b", re.I)


def apply_control():
    """Every control mutates PRODUCTION state (the shipped list or a shipped function), so a red run
    means the real gate caught a real defect shape — not that the test broke its own copy."""
    if CONTROL == "no-rollforward":
        def naive(month, day, today):
            try:
                return date(today.year, month, day)
            except (TypeError, ValueError):
                return None
        policy._next_occurrence = naive
    elif CONTROL == "fixed-year":
        config.POLICY_CALENDAR = list(config.POLICY_CALENDAR) + [{
            "month": 11, "day": 30, "year": 2026, "key": "control-fixed-year",
            "label": "FHFA conforming loan limit for 2027 — expected November 2026",
            "note": "control entry", "url": "https://www.fhfa.gov/",
        }]
    elif CONTROL == "blank-note":
        config.POLICY_CALENDAR = list(config.POLICY_CALENDAR) + [{
            "month": 6, "day": 1, "key": "control-blank-note",
            "label": "Something — expected in June",
            "note": "", "url": "https://www.irs.gov/",
        }]
    elif CONTROL == "no-sort":
        policy._calendar_sort_key = lambda entry: 0
    elif CONTROL == "long-expiry":
        config.POLICY_ANNOUNCED = list(config.POLICY_ANNOUNCED) + [{
            "key": "fhfa-conforming-loan-limit", "announced": "2026-11-24",
            "expires": "2027-11-24", "label": "control entry", "note": "control entry",
            "url": "http://www.fhfa.gov/",
        }]
    elif CONTROL:
        print(f"INFRA: unknown POLICY_CALENDAR_CONTROL={CONTROL!r}", file=sys.stderr)
        sys.exit(3)


def main():
    apply_control()
    failures = []
    entries = config.POLICY_CALENDAR
    fp = {"entries": len(entries), "horizon_days": config.POLICY_CALENDAR_HORIZON_DAYS,
          "control": CONTROL or None}

    if not entries:
        print("FAIL: 09-policy-calendar — POLICY_CALENDAR is empty", file=sys.stderr)
        sys.exit(1)

    # --- C2 + C3 + C5: shape, no fixed years, anticipatory labels ---------------------------
    for i, e in enumerate(entries):
        tag = f"entry[{i}] {str(e.get('label'))[:50]!r}"

        for key in ("year", "date", "years"):
            if key in e:
                failures.append(f"C2 {tag} carries a {key!r} key — an entry must be a month/day "
                                f"RULE so it rolls forward; a year is what goes stale")
        label = str(e.get("label") or "")
        if YEAR_RE.search(label):
            failures.append(f"C2 {tag} names a year in its label — same defect, one layer down")

        month, day = e.get("month"), e.get("day")
        if not (isinstance(month, int) and 1 <= month <= 12):
            failures.append(f"C3 {tag} has month={month!r}")
        if not (isinstance(day, int) and 1 <= day <= 31):
            failures.append(f"C3 {tag} has day={day!r}")
        if not label.strip():
            failures.append(f"C3 {tag} has an empty label")
        if not str(e.get("note") or "").strip():
            failures.append(f"C3 {tag} has an empty note — the note is what makes the entry "
                            f"actionable and carries its sourcing; a bare label is a rumour")
        url = str(e.get("url") or "")
        if not url.startswith("https://"):
            failures.append(f"C3 {tag} has url={url!r} — must be an https link a human can open")

        if "expected" not in label.lower():
            failures.append(f"C5 {tag} does not say 'expected' — the label must read as "
                            f"anticipatory, never as an announced fact")
        m = PRECISE_DATE_RE.search(label)
        if m:
            failures.append(f"C5 {tag} states the precise date {m.group(0)!r} — exact dates move "
                            f"year to year and no source has announced this one. Put it in `note`")

    # --- C1: every entry resolves forward, from every reference date -------------------------
    worst = None
    for ref in REFERENCE_DATES:
        for e in entries:
            when = policy._next_occurrence(e.get("month"), e.get("day"), ref)
            tag = f"{str(e.get('label'))[:50]!r} from {ref.isoformat()}"
            if when is None:
                failures.append(f"C1 {tag} does not resolve at all")
                continue
            if when < ref:
                failures.append(f"C1 {tag} resolves to {when.isoformat()} — IN THE PAST. A "
                                f"month/day entry must roll into next year once it has passed")
            elif when > ref + timedelta(days=366):
                failures.append(f"C1 {tag} resolves to {when.isoformat()} — more than a year out, "
                                f"so it can never enter the horizon (an impossible month/day?)")
            gap = (when - ref).days
            if worst is None or gap > worst[0]:
                worst = (gap, str(e.get("label"))[:50], ref.isoformat(), when.isoformat())
    fp["max_days_to_next_occurrence"] = worst

    # --- C4: ascending order out of the horizon filter ---------------------------------------
    # Nov 1 is the densest window in the shipped calendar (four entries), and config lists them in
    # the OPPOSITE order to their dates — which is what gives the `no-sort` control something to
    # break. If that ever stops being true the control is vacuous, so say so rather than pass quietly.
    order_checked = 0
    for ref in REFERENCE_DATES + [date(2027, 11, 1), date(2027, 10, 15)]:
        got = policy.upcoming_calendar(ref)
        dates = [g["date"] for g in got]
        if len(dates) > 1:
            order_checked += 1
            if dates != sorted(dates):
                failures.append(f"C4 upcoming_calendar({ref.isoformat()}) returned {dates} — "
                                f"not ascending; 'What's coming' must read soonest-first")
    fp["order_windows_checked"] = order_checked
    if order_checked == 0:
        print("NOTE: no reference date produced 2+ entries — C4 did not engage", file=sys.stderr)
    if CONTROL == "no-sort" and order_checked == 0:
        print("INFRA: the no-sort control cannot engage (no multi-entry window)", file=sys.stderr)
        sys.exit(3)

    # --- C6: the horizon keeps the block INTERMITTENT ----------------------------------------
    # Walk a full year of real run dates and count the mornings on which the block would appear.
    start = date(2027, 1, 1)
    days = [start + timedelta(days=n) for n in range(365)]
    hit = sum(1 for d in days if policy.upcoming_calendar(d))
    pct = 100.0 * hit / len(days)
    fp["visible_days_per_year"] = {"days": hit, "pct": round(pct, 1)}
    if not 15.0 <= pct <= 75.0:
        failures.append(f"C6 the calendar block would appear on {hit}/365 mornings ({pct:.1f}%) — "
                        f"outside 15-75%. Under 15% it is not worth the surface; over 75% it has "
                        f"silently turned 'Policy that affects you' into an always-on section, "
                        f"undoing the render-when-non-empty decision")

    # --- C7: announced lines carry a url and an expiry, and really replace their calendar line ----
    cal_keys = [e.get("key") for e in entries]
    if len(set(cal_keys)) != len(cal_keys) or not all(cal_keys):
        failures.append(f"C7 calendar keys must be present and unique (got {cal_keys}): an announced "
                        f"line finds the entry it replaces by key")
    max_days = config.POLICY_ANNOUNCED_MAX_DAYS
    announced = list(getattr(config, "POLICY_ANNOUNCED", []) or [])
    for a in announced:
        tag = f"announced[{a.get('key')!r}]"
        url = str(a.get("url") or "")
        if not url.startswith("https://"):
            failures.append(f"C7 {tag} has url={url!r}: an announced fact must link its https "
                            f"primary source")
        if a.get("key") not in cal_keys:
            failures.append(f"C7 {tag} matches no POLICY_CALENDAR key, so it replaces nothing")
        if not str(a.get("label") or "").strip() or not str(a.get("note") or "").strip():
            failures.append(f"C7 {tag} has an empty label or note")
        try:
            ann = date.fromisoformat(a["announced"])
            exp = date.fromisoformat(a["expires"])
        except Exception as e:                       # noqa: BLE001
            failures.append(f"C7 {tag} needs ISO `announced` and `expires` dates ({e})")
            continue
        if exp < ann:
            failures.append(f"C7 {tag} expires {exp} before it was announced {ann}")
        elif (exp - ann).days > max_days:
            failures.append(f"C7 {tag} expires {(exp - ann).days} days after it was announced, past "
                            f"the {max_days}-day limit: a dated fact must not outlive its season "
                            f"and shadow next year's 'expected' line")
        rows = policy.upcoming_calendar(ann)
        if not any(r.get("announced") == a["announced"] and r.get("label") == a.get("label")
                   for r in rows):
            failures.append(f"C7 {tag} does not appear in upcoming_calendar({ann}) on its own "
                            f"announcement day: the replacement is not wired")
        after = policy.upcoming_calendar(exp + timedelta(days=1))
        if any(r.get("label") == a.get("label") for r in after):
            failures.append(f"C7 {tag} still shows the day after it expires ({exp})")
    fp["announced_entries"] = len(announced)

    if failures:
        print("FAIL: 09-policy-calendar", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    if CONTROL:
        print(f"NOTE: control {CONTROL!r} did NOT go red — it has stopped measuring anything",
              file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(HERE, "09-policy-calendar.fingerprint.json"), "w", encoding="utf-8") as fh:
        json.dump(fp, fh, indent=2)
    print(f"PASS: 09-policy-calendar — C1..C7 ({len(entries)} entries, horizon "
          f"{config.POLICY_CALENDAR_HORIZON_DAYS}d; all resolve forward from "
          f"{len(REFERENCE_DATES)} reference dates incl. Dec 31/Jan 1; no fixed years; "
          f"{order_checked} multi-entry windows all ascending; block visible {hit}/365 days "
          f"= {pct:.1f}% of mornings; {len(announced)} announced line(s) with an expiry within "
          f"{max_days} days)")


if __name__ == "__main__":
    main()
