#!/usr/bin/env python3
"""
ASSUMPTION 12 (the two narrations cannot drift apart): the briefing is spoken by TWO independent
implementations of the same script — `scripts/tts.py compose_script()`, which becomes the daily mp3,
and `docs/app.js speechText()`, which the phone reads in its own voice whenever there is no mp3 (a
day the build's TTS failed, an archived edition, offline). They are hand-mirrored, and until this
file existed the only thing holding them together was a comment on each side saying "mirror any
change in the other". A comment is a label, not a mechanism.

WHY IT EARNS A MACHINE. The failure is SILENT and it RECURS. Silent: nothing in production ever
compares the two, so a fallback day just quietly becomes a different briefing — a listener would have
to notice that the number they heard on Tuesday was missing on Wednesday and correctly attribute it
to which voice was reading. Recurring: every future edit to the narration has to be made twice, by
hand, in two languages. That is exactly the two-part gate this project uses to decide a failure
deserves a runnable check instead of a note.

This is not hypothetical. The 2026-08-20 change (the 10-year / 30-year mortgage / VIX readout with
their reasons, the Monday policy digest, and the tech-vs-world dedupe) added ~120 lines that had to
land identically on both sides, including one genuine cross-language trap the gate pins down:
Python's `date.weekday()` is Monday=0 while JavaScript's `Date.getDay()` is Sunday=0, so "Monday"
is the constant 0 in config.py and the constant 1 in app.js. Those two disagreeing would silently
move the weekly policy digest to a different day in the device voice than in the mp3.

  (C1) BYTE EQUALITY — for every fixture, compose_script() and speechText() return the identical
       string. Fixtures cover the branches that differ: Monday vs a non-Monday, a present vs an
       absent mortgage block, null `change` on every number (the "level known, delta unknown" shape
       market.py deliberately produces), a Sunday recap, a duplicate story filed in both tech and
       world, a lesson hand-off vs a sign-off, and a fully degraded briefing with nothing in it.
  (C2) THE BRANCHES ACTUALLY FIRE — the fixtures are asserted to EXERCISE what they claim, so C1
       cannot pass by comparing two identically empty strings. The Monday fixture must really emit
       the digest, the non-Monday one must really omit it, the dedupe fixture must really drop an
       item, and the rates fixture must really speak all three figures.

Runnable NOW (no API key, no network; needs `node`, which data-smoke.yml already installs for
11-client-pointer.js). Read-only. Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA (no node).

NEGATIVE CONTROLS (`NARRATION_MIRROR_CONTROL=<mode>`) — each breaks the PYTHON side and must drive
C1 red, proving the comparison is really measuring these three behaviours and not just agreeing that
two strings are both empty. All three verified red at authoring time, 2026-08-20:
  drop-rates   -> the rates readout vanishes from the mp3 script but not from the device voice.
  drop-policy  -> the Monday policy digest vanishes from the mp3 script but not from the device voice.
  no-dedupe    -> the mp3 script reads a cross-filed story twice; the device voice reads it once.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
CONTROL = os.environ.get("NARRATION_MIRROR_CONTROL", "").strip()

APP_JS = os.path.join(REPO, "docs", "app.js")

# The two markers the extractor slices `docs/app.js` between. Named here so that renaming a block in
# app.js fails LOUDLY in this gate rather than silently extracting nothing and comparing empties.
JS_BLOCK_START = "// ---- Narration mirror"
JS_BLOCK_END = "function speakChunked(text, onDone) {"
JS_HELPER_START = "function localDate(iso) {"
JS_HELPER_END = "function safeHref(url) {"

# A node program that evaluates ONLY the narration mirror out of the real docs/app.js — no browser,
# no DOM, no network. Reads [{briefing, hasLesson}] and prints the narrations as JSON.
NODE_SHIM = """
const fs = require("fs");
const [appPath, fixPath, S, E, HS, HE] = process.argv.slice(2);
const src = fs.readFileSync(appPath, "utf8");
function slice(a, b, what) {
  const i = src.indexOf(a), j = src.indexOf(b);
  if (i < 0 || j < 0 || j <= i) {
    console.error("MARKER-MISSING:" + what);
    process.exit(9);
  }
  return src.slice(i, j);
}
const code = slice(HS, HE, "localDate") + "\\n" + slice(S, E, "narration-mirror");
const mod = { exports: {} };
new Function("module", code + "\\nmodule.exports = { speechText };")(mod);
const fixtures = JSON.parse(fs.readFileSync(fixPath, "utf8"));
console.log(JSON.stringify(fixtures.map((f) => mod.exports.speechText(f.briefing, f.hasLesson))));
"""


def _num(value, change, asof, why=""):
    return {"value": value, "change": change, "asof": asof, "why": why}


def _item(summary, source, url):
    return {"summary": summary, "source": source, "url": url}


# One story, filed under two different outlets with two different URLs and reworded — the shape the
# overlap test exists for. A URL match alone would not catch this.
DUP_TECH = _item(
    "LG Display introduced FLiPP, a new OLED manufacturing method designed to produce brighter, "
    "more efficient and longer-lasting display panels.", "The Verge", "https://example.com/a")
DUP_WORLD = _item(
    "A new OLED manufacturing method from LG Display, called FLiPP, produces brighter and more "
    "efficient longer-lasting display panels.", "Reuters", "https://example.com/b")

POLICY_ITEM = {
    "what_happened": "A federal rule updates flood insurance disclosure.",
    "effect": "You will see a flood-risk disclosure before closing on a home.",
    "url": "https://example.gov/flood", "status": "Final rule",
    "effective_date": "2026-11-01", "source": "Federal Register",
}
UPCOMING_ITEM = {
    "what_happened": "A Utah bill changes the property tax exemption process.",
    "effect": "You will have a filing deadline with the county board of equalization.",
    "url": "https://example.gov/utah", "status": "Signed in Utah",
    "effective_date": "2027-01-01", "source": "Utah Legislature",
}

FULL_MARKET = {"sp500": _num(7707.98, 16.22, "2026-08-19"),
               "ndx": _num(26331.09, 41.38, "2026-08-19"),
               "why": "Indices closed higher on broad participation."}

# 2026-08-17 is a Monday and 2026-08-18 a Tuesday; 2026-08-23 is a Sunday. Fixed dates, not
# computed ones, so the gate reads the same on every day it is ever run.
FIXTURES = [
    {"name": "monday-full", "hasLesson": True, "briefing": {
        "date": "2026-08-17", "tldr": ["The first thing that matters today.",
                                       "The second thing that matters today."],
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, -0.05, "2026-08-19", "Yields eased after a Treasury buyback plan."),
        "vix": _num(14.89, -0.95, "2026-08-19", "Volatility drifted lower into the close."),
        "mortgage": _num(6.67, -0.02, "2026-08-13", "Mortgage rates followed the 10-year lower."),
        "policy_week": [POLICY_ITEM], "policy_upcoming": [UPCOMING_ITEM],
        "tech": [DUP_TECH], "world": [DUP_WORLD, _item("An unrelated global event occurred in Kyiv "
                                                       "overnight.", "Guardian", "https://e.com/c")],
    }},
    {"name": "tuesday-no-mortgage", "hasLesson": False, "briefing": {
        "date": "2026-08-18", "tldr": ["Only one takeaway today."],
        "market": FULL_MARKET,
        "yield_10y": _num(4.70, 0.05, "2026-08-19", "Yields backed up."),
        "vix": _num(15.10, 0.21, "2026-08-19", "Hedging demand picked up."),
        "mortgage": None,
        "policy_week": [POLICY_ITEM], "policy_upcoming": [UPCOMING_ITEM],
        "tech": [_item("A chip fabricator announced a new node.", "Verge", "https://e.com/d")],
        "world": [_item("An election concluded in Brazil.", "Guardian", "https://e.com/e")],
    }},
    {"name": "null-changes", "hasLesson": True, "briefing": {
        "date": "2026-08-19", "tldr": [],
        "market": {"sp500": _num(7707.98, None, "2026-08-19"),
                   "ndx": _num(26331.09, None, "2026-08-19"), "why": ""},
        "yield_10y": _num(4.65, None, "2026-08-19", ""),
        "vix": _num(14.89, None, "2026-08-19", ""),
        "mortgage": _num(6.67, None, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "world": [],
    }},
    {"name": "sunday-recap", "hasLesson": False, "briefing": {
        "date": "2026-08-23", "tldr": ["A Sunday takeaway."],
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, -0.05, "2026-08-19", "Yields eased."),
        "vix": _num(14.89, -0.95, "2026-08-19", "Volatility fell."),
        "mortgage": _num(6.67, -0.02, "2026-08-13", "Rates followed yields."),
        "policy_week": [POLICY_ITEM], "policy_upcoming": [],
        "tech": [], "world": [],
        "weekly_recap": "A short zoom-out of the week just gone and the week ahead.",
    }},
    {"name": "monday-quiet-policy", "hasLesson": False, "briefing": {
        "date": "2026-08-17", "tldr": ["A quiet policy week."],
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, 0.0, "2026-08-19", ""),
        "vix": _num(14.89, -0.95, "2026-08-19", ""),
        "mortgage": _num(6.67, 0.0, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "world": [],
    }},
    {"name": "flat-vix", "hasLesson": False, "briefing": {
        "date": "2026-08-19", "tldr": ["A flat day."],
        "market": {"sp500": _num(7707.98, 0.001, "2026-08-19"),
                   "ndx": _num(26331.09, 0.001, "2026-08-19"), "why": ""},
        "yield_10y": _num(4.65, 0.0, "2026-08-19", ""),
        # A VIX move that rounds to 0.0% — the shape that must not be read as "up 0.0 percent".
        "vix": _num(14.89, 0.004, "2026-08-19", ""),
        "mortgage": _num(6.67, -0.02, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "world": [],
    }},
    {"name": "degraded-empty", "hasLesson": False, "briefing": {
        "date": "", "tldr": [], "market": {}, "yield_10y": None, "vix": None, "mortgage": None,
        "policy_week": [], "policy_upcoming": [], "tech": [], "world": [],
    }},
]


def _apply_control(tts):
    """Break the PYTHON narration in one specific way, so C1 must go red."""
    if CONTROL == "drop-rates":
        tts._rate_lines = lambda briefing: []
    elif CONTROL == "drop-policy":
        tts._policy_lines = lambda briefing, weekday: []
    elif CONTROL == "no-dedupe":
        tts._dedupe_across = lambda buckets: [(label, list(items or []))
                                              for label, items in buckets]
    elif CONTROL:
        print(f"REFUSED: unknown NARRATION_MIRROR_CONTROL {CONTROL!r}", file=sys.stderr)
        sys.exit(2)


def main():
    if os.environ.get(GATE) != "true":
        print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
        sys.exit(2)
    node = shutil.which("node")
    if not node:
        print("INFRASTRUCTURE FAIL: `node` is not on PATH — this gate compares the real "
              "docs/app.js narration against the Python one and cannot run without it",
              file=sys.stderr)
        sys.exit(3)

    from scripts import tts
    _apply_control(tts)

    py = [tts.compose_script(f["briefing"], has_lesson=f["hasLesson"]) for f in FIXTURES]

    with tempfile.TemporaryDirectory() as tmp:
        fix_path = os.path.join(tmp, "fixtures.json")
        shim_path = os.path.join(tmp, "shim.js")
        with open(fix_path, "w", encoding="utf-8") as fh:
            json.dump([{"briefing": f["briefing"], "hasLesson": f["hasLesson"]} for f in FIXTURES], fh)
        with open(shim_path, "w", encoding="utf-8") as fh:
            fh.write(NODE_SHIM)
        proc = subprocess.run(
            [node, shim_path, APP_JS, fix_path, JS_BLOCK_START, JS_BLOCK_END,
             JS_HELPER_START, JS_HELPER_END],
            capture_output=True, text=True, timeout=60)

    if proc.returncode == 9:
        print(f"FAIL: 12-narration-mirror — {proc.stderr.strip()}", file=sys.stderr)
        print("  - docs/app.js no longer contains the expected narration-mirror markers, so the "
              "two narrations can no longer be compared at all", file=sys.stderr)
        sys.exit(1)
    if proc.returncode != 0:
        print(f"FAIL: 12-narration-mirror — the node extractor exited {proc.returncode}",
              file=sys.stderr)
        print((proc.stderr or "").strip()[:2000], file=sys.stderr)
        sys.exit(1)

    js = json.loads(proc.stdout)
    failures = []

    # --- C1: byte equality, fixture by fixture ---------------------------------------------------
    for f, a, b in zip(FIXTURES, py, js):
        if a != b:
            where = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            failures.append(
                f"C1 {f['name']}: the two narrations differ at character {where}.\n"
                f"      python: ...{a[max(0, where - 60):where + 120]!r}\n"
                f"      js    : ...{b[max(0, where - 60):where + 120]!r}")

    # --- C2: the fixtures actually exercise the branches they are named for ----------------------
    by_name = dict(zip((f["name"] for f in FIXTURES), py))
    checks = [
        ("monday-full", "This week, in policy that affects you.", True,
         "the Monday fixture did not emit the weekly policy digest, so C1 proved nothing about it"),
        ("monday-full", "flood-risk disclosure", True,
         "the Monday digest did not read the week's item"),
        ("monday-full", "Still ahead of you.", True,
         "the Monday digest did not read the forward-looking items"),
        ("tuesday-no-mortgage", "This week, in policy that affects you.", False,
         "the non-Monday fixture emitted the digest, so the weekday gate is not holding"),
        ("tuesday-no-mortgage", "30-year fixed mortgage", False,
         "the absent-mortgage fixture still spoke a mortgage line"),
        ("monday-full", "The 10-year Treasury yield is 4.65 percent, down 5 basis points.", True,
         "the rates readout did not speak the 10-year"),
        ("monday-full", "The 30-year fixed mortgage is 6.67 percent", True,
         "the rates readout did not speak the mortgage"),
        ("monday-full", "The VIX is 14.89, down 6.0 percent.", True,
         "the rates readout did not speak the VIX"),
        ("monday-quiet-policy", "No new rules or bills landed for you this week.", True,
         "a quiet policy week said nothing at all, which is indistinguishable from a broken section"),
        ("sunday-recap", "Your weekly recap.", True, "the Sunday fixture lost its recap"),
        ("null-changes", "basis points", False,
         "a null change still produced a move, so the unknown-delta shape is not being honoured"),
        ("flat-vix", "The VIX is 14.89, essentially unchanged.", True,
         "a VIX move that rounds to 0.0% was still read aloud as a move with a direction"),
        ("flat-vix", "0.0 percent", False,
         "a move that rounds to zero was still read aloud as \"0.0 percent\" with a direction"),
        ("flat-vix", "essentially unchanged", True,
         "the flat 10-year move was not collapsed either"),
    ]
    for name, needle, want, why in checks:
        if (needle in by_name[name]) is not want:
            failures.append(f"C2 {name}: {why}")

    # The dedupe must really have dropped the cross-filed story from `world`.
    monday = by_name["monday-full"]
    if monday.count("FLiPP") != 1:
        failures.append(
            f"C2 monday-full: the cross-filed story appears {monday.count('FLiPP')} times, expected "
            f"exactly 1 — the tech/world dedupe did not fire, so C1 proved nothing about it")
    if "Kyiv" not in monday:
        failures.append("C2 monday-full: the dedupe removed a genuinely distinct world item")

    if failures:
        print("FAIL: 12-narration-mirror", file=sys.stderr)
        for f in failures:
            print("  -", f, file=sys.stderr)
        sys.exit(1)

    if CONTROL:
        print(f"NOTE: control {CONTROL!r} did NOT go red — it has stopped measuring anything",
              file=sys.stderr)
        sys.exit(1)

    print(f"PASS: 12-narration-mirror — C1..C2 ({len(FIXTURES)} fixtures byte-identical across "
          f"scripts/tts.py and docs/app.js; Monday digest fires and non-Monday does not; all three "
          f"rate figures spoken; cross-filed story read once)")


if __name__ == "__main__":
    main()
