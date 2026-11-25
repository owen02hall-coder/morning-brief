#!/usr/bin/env python3
"""
ASSUMPTION 13 (the US section reports events, never the contest about them): `summarize.SYSTEM`
excluded US politics outright until 2026-08-20 — "World news: only globally significant events, not
granular or partisan US politics" — because a blanket exclusion is the cheapest possible defence
against a briefing that turns into partisan shouting. That exclusion also meant a Supreme Court
ruling, a hurricane landfall or a product recall reached this reader NOWHERE, so the category was
re-admitted as its own section under a narrower rule: report EVENTS AND OUTCOMES, never the CONTEST.

Relaxing a safety rule is the moment it needs a machine. The failure is silent — a partisan item
renders exactly like a good one, and the only detector is the reader slowly deciding the section is
not worth listening to — and it recurs daily, because it depends on a model's judgement over
whatever the wires happen to be carrying. Silent and recurring is this project's two-part gate for
spending code on a guard.

Measured at authoring time: 18 of 19 live AP + NPR National candidates carried NO contest
vocabulary, and the one that did was "The Iran war and tariffs are costing farmers. Will Republicans
pay in..." — a pure horse-race framing. So the feeds are overwhelmingly event desks (which is why
Guardian US, whose top item was "Melania Trump appears to nod to questions about absence", was
rejected rather than merely unused) AND the rule has real work to do.

  (C1) THE DETECTOR WORKS — it fires on seeded contest copy and stays silent on seeded event copy.
       Without this, C3/C4 could pass forever by matching nothing, which is how a guard rots.
  (C2) THE RULE IS STILL IN THE PROMPT — `summarize.SYSTEM` carries the US NEWS RULE and its
       attack-verb list. A prompt refactor that drops it would otherwise be invisible until the
       section had already drifted.
  (C3) THE MODEL OBEYS IT — a live call over real AP/NPR candidates returns `us` items free of
       contest vocabulary. Skipped (not failed) without GEMINI_API_KEY. Since 2026-11-25 production
       drops contest items itself (summarize._drop_contest_us), so C3's hard check proves the
       shipped guard holds and a NOTE reports how many items the guard had to drop.
  (C4) SHIPPED EDITIONS ARE CLEAN — every archived briefing that has a `us` section is checked.
       Starts as a no-op and grows into a real regression net as archives accumulate.

Runnable NOW (C1/C2/C4 need no key and no network). Read-only.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.

NEGATIVE CONTROLS (`US_EDITORIAL_CONTROL=<mode>`), both verified red at authoring time 2026-08-20:
  blunt-detector -> C1 red. Replaces the pattern with one that matches nothing, i.e. the exact way
                    this gate would decay into a rubber stamp.
  drop-rule      -> C2 red. Strips the US NEWS RULE out of the SYSTEM text before checking it.
"""
import datetime
import json
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
CONTROL = os.environ.get("US_EDITORIAL_CONTROL", "").strip()

if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

try:
    from scripts import config, summarize
    from scripts.data import news as news_mod
except Exception as e:                                  # noqa: BLE001 - any import failure is INFRA
    print(f"INFRA: could not import the production surface ({type(e).__name__}: {e})",
          file=sys.stderr)
    sys.exit(3)

# The contest vocabulary, its carve-outs and contest_hits() moved to scripts/summarize.py on
# 2026-11-25, where they now also GUARD the shipped US section (summarize._drop_contest_us): C4 went
# red five weeks running on items the prompt rule should have kept out, and a prompt instruction is
# a label, not a mechanism. The history of every carve-out moved with the code. This file imports the
# ONE detector, so the gate and production cannot drift apart (the same rule as _MONEY).
from scripts.summarize import contest_hits  # noqa: E402

C4_WINDOW_DAYS = 7    # data-smoke.yml runs weekly; one window per run (see C4)

EVENT_COPY = [
    "A federal appeals court ruled that the state may not enforce the statute while litigation "
    "continues.",
    "A recall was issued for a household appliance after reports of overheating.",
    "Hurricane made landfall on the Gulf coast, and evacuation orders remain in place for three "
    "counties.",
    "Harvard agreed to a 53 million dollar settlement over body parts taken from its morgue.",
    "Health officials linked an outbreak of food poisoning to alfalfa sprouts sold in two states.",
    # The 2026-08-31 false positive, kept verbatim as the regression it is: party as BIOGRAPHY in a
    # story that is about a betting platform, not about a fight.
    "Former Republican congressman George Santos has received a lifetime ban from the "
    "prediction-market platform Kalshi after an investigation into wash trading.",
    "A Democratic senator was named in the indictment unsealed by federal prosecutors on Tuesday.",
    # The second false positive, kept verbatim: "the polls" as a PLACE, in a civil-military story.
    "The US military's top general stated there are no plans to send troops to the polls for the "
    "November elections.",
    "Two polling places in the county were relocated after the building failed a safety inspection.",
    # The third false positive, kept verbatim: "midterm elections" as a DATE, in the same
    # civil-military story that produced the second one.
    "The top U.S. general confirmed that there are no plans to deploy military troops to polling "
    "sites for the upcoming midterm elections.",
    # The 2026-10-21 pair, kept verbatim (both shipped, and C4 re-flagged them for weeks).
    "The Supreme Court rejected the Trump administration's request to implement new mail-in voting "
    "restrictions for the midterm general election.",
    "Dennis Hastert, who served as the longest-serving Republican House speaker before his political "
    "legacy was marred by scandal, has died.",
]
CONTEST_COPY = [
    "Critics slammed the decision, and Democrats said they would fight it in the midterms.",
    "The governor hit back at Republicans, doubling down on his earlier comments.",
    "Polling shows the measure is deeply partisan, with approval ratings split along party lines.",
    "The backlash was immediate, and the campaign trail feud escalated over the weekend.",
    # The other side of the carve-out: the PLURAL collective must still fire, or BIOGRAPHICAL has
    # widened into "party names are always fine" and C3 stops measuring anything.
    "Republicans said the vote proved their point, and Democrats accused them of stalling.",
    # The other side of the polling carve-out: opinion polling is still the horse race.
    "A new poll shows the measure trailing by nine points, and polling has moved against it all "
    "month.",
    # The other side of the MIDTERM_DATE carve-out. Deliberately built so "midterms" is the ONLY
    # word here the detector can match — "parties" and "fight" are not in CONTEST — so this control
    # fails the moment the carve-out widens from the noun phrase to the bare word.
    "Both parties are pouring money into the midterms as they fight for control of the chamber.",
]


def main():
    failures, notes = [], []

    if CONTROL == "blunt-detector":
        # Patches PRODUCTION's pattern: contest_hits (imported from summarize) reads it at call time,
        # so this is the exact decay that would also switch off the shipped guard.
        summarize.CONTEST = re.compile(r"\bzzzz-nothing-matches-this\b", re.I)
    elif CONTROL == "drop-rule":
        pass
    elif CONTROL:
        print(f"REFUSED: unknown US_EDITORIAL_CONTROL {CONTROL!r}", file=sys.stderr)
        sys.exit(2)

    # --- C1: the detector actually discriminates -------------------------------------------------
    for copy in EVENT_COPY:
        hits = contest_hits(copy)
        if hits:
            failures.append(f"C1 the detector fired on EVENT copy {copy[:60]!r} -> {hits}; it is "
                            f"too broad and would suppress exactly the items this section is for")
    for copy in CONTEST_COPY:
        if not contest_hits(copy):
            failures.append(f"C1 the detector stayed SILENT on CONTEST copy {copy[:60]!r} — it has "
                            f"stopped measuring anything, so C3/C4 below prove nothing")

    # --- C2: the rule is still in the production prompt -------------------------------------------
    system = summarize.SYSTEM
    if CONTROL == "drop-rule":
        system = system.replace("US NEWS RULE", "(removed by control)")
    for needle, why in [
        ("US NEWS RULE", "the rule's heading is gone from summarize.SYSTEM"),
        ("EVENTS AND OUTCOMES", "the events-not-contest instruction is gone"),
        ("slammed", "the attack-verb examples are gone, which is what makes the rule concrete"),
    ]:
        if needle not in system:
            failures.append(f"C2 {why} — the US section would be governed by nothing")

    if "us" not in str(getattr(summarize.Narrative, "model_fields", {})):
        failures.append("C2 the Narrative schema has no `us` field — the section cannot be produced")

    # --- C3: the model obeys it, over real wire copy ----------------------------------------------
    if not os.environ.get("GEMINI_API_KEY"):
        notes.append("NOTE C3 SKIPPED (no GEMINI_API_KEY): the live-model half did not run. C1, C2 "
                     "and C4 still ran and are what failed or passed above.")
    else:
        try:
            news = news_mod.get_news()
            if not news["us"]:
                notes.append("NOTE C3 SKIPPED: the US feeds returned nothing inside the window, so "
                             "there was no live copy to judge. Not treated as a failure here — "
                             "04-external-boundary-smoke owns feed liveness.")
            else:
                narrative, ok = summarize.summarize(
                    {"sp500": None, "ndx": None, "vix": None, "ten_year": None},
                    news, False, mortgage=None)
                if not ok:
                    notes.append("NOTE C3 SKIPPED: the model call failed; 03-gemini-structured owns "
                                 "model availability.")
                else:
                    items = narrative.get("us") or []
                    if not items:
                        notes.append(f"NOTE C3 the model returned no US items from "
                                     f"{len(news['us'])} candidates — not a failure (a day of pure "
                                     f"contest coverage SHOULD produce nothing), but worth watching.")
                    for it in items:
                        hits = contest_hits(f"{it.get('summary','')}")
                        if hits:
                            failures.append(
                                f"C3 a live US item carries contest vocabulary {hits}: "
                                f"{it.get('summary','')[:110]!r} — the events-not-contest rule is "
                                f"not holding against real wire copy")
                    # Counted from THIS check's own findings, not assumed. Until 2026-08-31 this
                    # line said "all clean" unconditionally and a real run printed the failure and
                    # "all clean" together — a report that contradicts itself teaches the reader to
                    # believe neither half.
                    dirty = sum(1 for it in items if contest_hits(f"{it.get('summary','')}"))
                    verdict = "all clean" if not dirty else f"{dirty} carrying contest vocabulary"
                    notes.append(f"NOTE C3 ran: {len(items)} US item(s) from {len(news['us'])} "
                                 f"live candidates, {verdict}.")
                    # Since 2026-11-25 summarize._drop_contest_us removes contest items before they
                    # ship, so the hard check above proves the GUARD holds on live copy. How often
                    # the MODEL broke the rule is still worth tracking, so it is reported here.
                    drops = summarize.last_us_contest_drops()
                    notes.append(f"NOTE C3 the shipped guard dropped {len(drops)} US item(s) the "
                                 f"model wrote with contest vocabulary"
                                 + (f": {[h for h, _ in drops]}" if drops else "."))
        except Exception as e:                          # noqa: BLE001
            notes.append(f"NOTE C3 SKIPPED (infrastructure): {type(e).__name__}: {e}")

    # --- C4: shipped editions ---------------------------------------------------------------------
    # Only the editions since the last weekly run. A shipped edition never changes, so re-reading the
    # last 30 meant ONE keyword hit kept this run red for four straight weeks (2026-09-14..10-12, all
    # false positives, zero true ones) — and a weekly page that is always red trains the reader to
    # ignore the week it is real. Each edition is now judged once, in the week it shipped.
    cutoff = (datetime.date.today() - datetime.timedelta(days=C4_WINDOW_DAYS)).isoformat()
    checked = 0
    for path in sorted(glob.glob(os.path.join(REPO, "docs", "archive", "*.json"))):
        if os.path.basename(path)[:10] <= cutoff:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                b = json.load(fh)
        except Exception:                               # noqa: BLE001 - a corrupt archive is not this gate's job
            continue
        if not isinstance(b, dict) or not b.get("us"):
            continue
        checked += 1
        for it in b["us"]:
            hits = contest_hits(it.get("summary") or "")
            if hits:
                failures.append(f"C4 shipped edition {b.get('date')} carries contest vocabulary "
                                f"{hits} in its US section: {(it.get('summary') or '')[:100]!r}")
    if checked == 0:
        notes.append(f"NOTE C4 no edition from the last {C4_WINDOW_DAYS} days carries a `us` section "
                     "— nothing was judged (the heartbeat, not this test, pages a stalled build).")

    for n in notes:
        print(n)

    if failures:
        print("FAIL: 13-us-news-editorial", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    if CONTROL:
        print(f"NOTE: control {CONTROL!r} did NOT go red — it has stopped measuring anything",
              file=sys.stderr)
        sys.exit(1)

    print(f"PASS: 13-us-news-editorial — C1..C4 (detector discriminates {len(EVENT_COPY)} event vs "
          f"{len(CONTEST_COPY)} contest samples; the rule is in summarize.SYSTEM; "
          f"{checked} archived edition(s) with a US section checked)")


if __name__ == "__main__":
    main()
