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
  no-tldr-cut  -> the mp3 script re-reads a story the must-knows already told; the device voice does
                  not. Guards the CONTAINMENT half specifically, which is a different metric from
                  the Jaccard used between buckets and could rot independently of it.
  drop-etfs    -> the watchlist vanishes from the mp3 script but not from the device
                  voice. (Added 2026-09-09 with the section; verified red.)
  etf-round    -> the mp3 script formats RSI with Python's "%.0f" instead of floor(x + 0.5), so an
                  RSI of exactly 48.5 is spoken as 48 in the mp3 and 49 in the phone's own voice.
                  The same cross-language shape as the Monday=0/Sunday=0 weekday split.
                  (Added 2026-09-09; verified red.)
  etf-nofilter -> the mp3 script names every ticker on the watchlist instead of only the buy/trim
                  ones, so it reads out a HOLD the phone's voice drops. The filter is the whole
                  point of the section for the listener, and it lives on both sides of the
                  language boundary. (Added 2026-09-09; verified red.)
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

tts_mod = None   # bound in main(); the control variants read the real spoken wording from it

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
CONTROL = os.environ.get("NARRATION_MIRROR_CONTROL", "").strip()

APP_JS = os.path.join(REPO, "docs", "app.js")

# The two markers the extractor slices `docs/app.js` between. Named here so that renaming a block in
# app.js fails LOUDLY in this gate rather than silently extracting nothing and comparing empties.
JS_BLOCK_START = "// ---- Narration mirror"
JS_BLOCK_END = "function speakChunked(text, rate, onDone) {"
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

US_ITEM = _item("A federal appeals court ruled that a state may not enforce its new licensing "
                "statute while litigation continues.", "AP", "https://example.com/us1")
# Deliberately a near-duplicate of DUP_WORLD's story, filed in the US bucket. US is narrated BEFORE
# world, so this must survive in "Across the country" and vanish from "Around the world" — which is
# what pins the bucket ORDER, not merely the existence of a dedupe.
US_DUP_OF_WORLD = _item(
    "A new OLED manufacturing method from LG Display named FLiPP produces brighter and more "
    "efficient longer-lasting display panels.", "AP", "https://example.com/us2")

# Four tickers covering every shape the section can take: a buy called by the band, a buy called by
# RSI alone, a trim, and a HOLD that BOTH sides must drop (the audio names only buy/trim tickers).
# Every row is internally consistent with scripts/data/watchlist.py — re-deriving zone/action from
# value/low/high/rsi reproduces the stated fields, verified 2026-09-09.
#
# The 48.5 RSI is the value where Python's "%.0f" (round-half-to-EVEN -> 48) and JavaScript's
# Math.round (half-up -> 49) disagree, and it sits on a ticker that is SPOKEN. It used to sit on the
# mid-range one; once the audio started naming only buy/trim tickers, that would have filtered the
# trap straight out of the comparison and left this gate passing while blind to it.
#
# AAPL is here for two reasons at once: the watchlist is the reader's to edit now (watchlist.txt)
# and is no longer ETF-only, and a HOLD row is what makes C1 actually measure the buy/trim filter —
# a side that forgot to filter would name it and the comparison would go red.
WATCHLIST = [
    {"symbol": "SOXL", "what": "3x semiconductors", "value": 108.90,
     "day_move": -2.11, "asof": "2026-08-19", "rsi": 48.5, "rsi_zone": "neutral",
     "low": 105.91, "high": 151.53, "band_pct": 6.6, "zone": "low", "action": "buy",
     "read": "Within 4% of its 1-month low."},
    {"symbol": "SPXL", "what": "3x S&P 500", "value": 293.00,
     "day_move": -1.67, "asof": "2026-08-19", "rsi": 28.4, "rsi_zone": "oversold",
     "low": 281.35, "high": 301.35, "band_pct": 58.3, "zone": "mid", "action": "buy",
     "read": "Oversold on RSI, mid-range for the month."},
    {"symbol": "TQQQ", "what": "3x Nasdaq-100", "value": 76.90,
     "day_move": 7.55, "asof": "2026-08-19", "rsi": 71.2, "rsi_zone": "overbought",
     "low": 69.01, "high": 77.15, "band_pct": 96.9, "zone": "high", "action": "trim",
     "read": "Within 4% of its 1-month high and overbought on RSI. Big session: up 7.6% in a day."},
    {"symbol": "AAPL", "what": "Apple", "value": 228.00,
     "day_move": 0.42, "asof": "2026-08-19", "rsi": 51.0, "rsi_zone": "neutral",
     "low": 220.00, "high": 235.00, "band_pct": 53.3, "zone": "mid", "action": "hold",
     "read": "Mid-range - 53% of the way up its 1-month band."},
]
# A day with nothing to do. Both sides must say so OUT LOUD rather than falling silent: a section
# that vanishes is indistinguishable from a section that broke.
WATCHLIST_QUIET = [WATCHLIST[3]]

FULL_MARKET = {"sp500": _num(7707.98, 16.22, "2026-08-19"),
               "ndx": _num(26331.09, 41.38, "2026-08-19"),
               "why": "Indices closed higher on broad participation."}

# 2026-08-17 is a Monday and 2026-08-18 a Tuesday; 2026-08-23 is a Sunday. Fixed dates, not
# computed ones, so the gate reads the same on every day it is ever run.
FIXTURES = [
    {"name": "monday-full", "hasLesson": True, "briefing": {
        "date": "2026-08-17", "tldr": ["The first thing that matters today.",
                                       "The second thing that matters today."],
        "watchlist": WATCHLIST,
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, -0.05, "2026-08-19", "Yields eased after a Treasury buyback plan."),
        "vix": _num(14.89, -0.95, "2026-08-19", "Volatility drifted lower into the close."),
        "mortgage": _num(6.67, -0.02, "2026-08-13", "Mortgage rates followed the 10-year lower."),
        "policy_week": [POLICY_ITEM], "policy_upcoming": [UPCOMING_ITEM],
        "tech": [], "science": [_item("A trial found a vaccine prevented cancer from returning in "
                                     "most participants.", "BBC Health", "https://e.com/sci1")],
        "us": [US_ITEM, US_DUP_OF_WORLD],
        "world": [DUP_WORLD, _item("An unrelated global event occurred in Kyiv "
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
        "us": [_item("A recall was issued for a household appliance.", "NPR National", "https://e.com/f")],
        "science": [],
        "world": [_item("An election concluded in Brazil.", "Guardian", "https://e.com/e")],
    }},
    {"name": "null-changes", "hasLesson": True, "briefing": {
        "date": "2026-08-19", "tldr": [],
        "market": {"sp500": _num(7707.98, None, "2026-08-19"),
                   "ndx": _num(26331.09, None, "2026-08-19"), "why": ""},
        "yield_10y": _num(4.65, None, "2026-08-19", ""),
        "vix": _num(14.89, None, "2026-08-19", ""),
        "mortgage": _num(6.67, None, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "us": [], "science": [], "world": [],
    }},
    {"name": "sunday-recap", "hasLesson": False, "briefing": {
        "date": "2026-08-23", "tldr": ["A Sunday takeaway."],
        "watchlist": WATCHLIST_QUIET,
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, -0.05, "2026-08-19", "Yields eased."),
        "vix": _num(14.89, -0.95, "2026-08-19", "Volatility fell."),
        "mortgage": _num(6.67, -0.02, "2026-08-13", "Rates followed yields."),
        "policy_week": [POLICY_ITEM], "policy_upcoming": [],
        "tech": [], "us": [], "science": [], "world": [],
        "weekly_recap": "A short zoom-out of the week just gone and the week ahead.",
    }},
    {"name": "monday-quiet-policy", "hasLesson": False, "briefing": {
        "date": "2026-08-17", "tldr": ["A quiet policy week."],
        "market": FULL_MARKET,
        "yield_10y": _num(4.65, 0.0, "2026-08-19", ""),
        "vix": _num(14.89, -0.95, "2026-08-19", ""),
        "mortgage": _num(6.67, 0.0, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "us": [], "science": [], "world": [],
    }},
    {"name": "flat-vix", "hasLesson": False, "briefing": {
        "date": "2026-08-19", "tldr": ["A flat day."],
        "market": {"sp500": _num(7707.98, 0.001, "2026-08-19"),
                   "ndx": _num(26331.09, 0.001, "2026-08-19"), "why": ""},
        "yield_10y": _num(4.65, 0.0, "2026-08-19", ""),
        # A VIX move that rounds to 0.0% — the shape that must not be read as "up 0.0 percent".
        "vix": _num(14.89, 0.004, "2026-08-19", ""),
        "mortgage": _num(6.67, -0.02, "2026-08-13", ""),
        "policy_week": [], "policy_upcoming": [], "tech": [], "us": [], "science": [], "world": [],
    }},
    {"name": "tldr-repeat", "hasLesson": False, "briefing": {
        "date": "2026-08-19",
        # The bullet is a COMPRESSION of the world item below — different wording, same story, and
        # the exact shape Jaccard misses (measured 0.26 on the real Indonesia earthquake pair).
        "tldr": ["A powerful 7.7-magnitude earthquake in eastern Indonesia killed at least 38 people."],
        "market": FULL_MARKET,
        "yield_10y": None, "vix": None, "mortgage": None,
        "policy_week": [], "policy_upcoming": [], "tech": [], "us": [], "science": [],
        "world": [
            _item("A powerful 7.7-magnitude earthquake struck eastern Indonesia, killing at least "
                  "38 people and prompting a tsunami warning along the coast.", "BBC",
                  "https://e.com/quake"),
            _item("Separately, a national election concluded peacefully in Brazil.", "Guardian",
                  "https://e.com/brazil"),
        ],
    }},
    {"name": "degraded-empty", "hasLesson": False, "briefing": {
        "date": "", "tldr": [], "market": {}, "yield_10y": None, "vix": None, "mortgage": None,
        "policy_week": [], "policy_upcoming": [], "tech": [], "us": [], "science": [], "world": [],
    }},
]


def _watchlist_lines_variant(briefing, naive_round=False, no_filter=False):
    """tts._watchlist_lines with exactly ONE difference injected, for the two ETF controls.

    Kept as one function with two flags rather than two near-copies: the controls have to differ
    from the real implementation in the single respect they are testing and in nothing else, or a
    red result would not point at the thing it claims to."""
    rows = briefing.get("watchlist") or []
    if not rows:
        return []
    acting = rows if no_filter else [r for r in rows if r.get("action") in tts_mod.ACTION_SPOKEN]
    if not acting:
        return ["Your watchlist. Nothing in buy or trim range today."]
    out = ["Your watchlist."]
    for r in acting:
        spelled = " ".join(r.get("symbol") or "")
        rsi = r.get("rsi")
        if rsi is None:
            head = f"{spelled}."
        elif naive_round:
            head = f"{spelled}, R S I {rsi:.0f}."
        else:
            head = f"{spelled}, R S I {math.floor(rsi + 0.5):d}."
        act = tts_mod.ACTION_SPOKEN.get(r.get("action"), "")
        read = (r.get("read") or "").strip()
        spoken = read.replace("%", " percent").replace(" - ", ", ")
        out.append(f"{head} {act} {spoken}".strip() if read else f"{head} {act}".strip())
    return out


def _apply_control(tts):
    """Break the PYTHON narration in one specific way, so C1 must go red."""
    if CONTROL == "drop-rates":
        tts._rate_lines = lambda briefing: []
    elif CONTROL == "drop-policy":
        tts._policy_lines = lambda briefing, weekday: []
    elif CONTROL == "no-dedupe":
        tts._dedupe_across = lambda buckets, tldr_words=(): [(label, list(items or []))
                                                            for label, items in buckets]
    elif CONTROL == "no-tldr-cut":
        tts._covered_by_tldr = lambda item, tldr_words: False
    elif CONTROL == "drop-etfs":
        tts._watchlist_lines = lambda briefing: []
    elif CONTROL == "etf-round":
        # The half-rounding split itself: Python's "%.0f" sends an RSI of 48.5 to the nearest EVEN
        # integer (48) while JavaScript's Math.round sends it up (49). Both sides use
        # floor(x + 0.5) precisely so they cannot disagree; this control puts the trap back.
        tts._watchlist_lines = lambda briefing: _watchlist_lines_variant(briefing, naive_round=True)
    elif CONTROL == "etf-nofilter":
        # The buy/trim filter itself. The listener asked to hear a ticker ONLY when there is
        # something to do about it, and that rule now lives on both sides of the language boundary,
        # so it needs a control of its own: here the mp3 script reads the HOLD ticker out and the
        # phone's voice still drops it.
        tts._watchlist_lines = lambda briefing: _watchlist_lines_variant(briefing, no_filter=True)
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
    global tts_mod
    tts_mod = tts        # the control variants read tts.ACTION_SPOKEN, the real spoken wording
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
        ("monday-full", "Health and science.", True,
         "the health/science section was not narrated"),
        ("monday-full", "vaccine prevented cancer", True,
         "the science section was announced but read none of its items"),
        ("degraded-empty", "Health and science.", False,
         "an empty science bucket still announced its heading"),
        ("monday-full", "Across the country.", True,
         "the US national section was not narrated at all"),
        ("monday-full", "federal appeals court ruled", True,
         "the US section was announced but read none of its items"),
        ("tuesday-no-mortgage", "Across the country.", True,
         "the US section vanished on a non-Monday, so it is wrongly coupled to the policy weekday"),
        ("degraded-empty", "Across the country.", False,
         "an empty US bucket still announced its heading, which would read as a broken section"),
        ("monday-full", "Your watchlist.", True,
         "the watchlist was not spoken at all, so C1 proved nothing about it"),
        ("monday-full", "Buy range.", True,
         "no ticker was called a buy, so the action the listener acts on never reached the audio"),
        ("monday-full", "Trim range.", True,
         "no ticker was called a trim, so only half the action vocabulary is being exercised"),
        # The HOLD ticker must be dropped by BOTH sides. C1 catches only a DISAGREEMENT about it;
        # this catches both sides quietly abandoning the filter together, which is the failure that
        # turns the section back into the four-ticker recital the reader asked it not to be.
        ("monday-full", "A A P L", False,
         "a hold ticker was read out — the audio is supposed to name only buy and trim"),
        ("sunday-recap", "Nothing in buy or trim range today.", True,
         "a day with no actionable ticker fell silent instead of saying so, which is "
         "indistinguishable from the section being broken"),
        # 49, not 48: floor(48.5 + 0.5) is what BOTH sides must produce. Python's "%.0f" would
        # say 48 here, which is exactly what the `etf-round` control puts back.
        ("monday-full", "R S I 49.", True,
         "the RSI 48.5 case did not reach the narration, so C1 is no longer measuring the "
         "Python-even / JavaScript-up half-rounding split that this fixture exists to pin"),
        ("monday-full", "Oversold on RSI, mid-range for the month.", True,
         "the watchlist read is not being spoken from the published `read` string, which is the "
         "only thing keeping the mp3, the device voice and the card from classifying differently"),
        ("degraded-empty", "Your watchlist.", False,
         "an edition with no watchlist data still announced the heading, which would read as a "
         "broken section on every archived briefing published before this feature existed"),
        ("tldr-repeat", "earthquake struck eastern Indonesia", False,
         "the world section re-read a story the must-knows had already told — this is the "
         "containment case Jaccard misses, so the tldr suppression is not working"),
        ("tldr-repeat", "election concluded peacefully in Brazil", True,
         "tldr suppression removed a genuinely DISTINCT item; it is over-matching"),
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
