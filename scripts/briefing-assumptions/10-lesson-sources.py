#!/usr/bin/env python3
"""
ASSUMPTION 10 (Owen's Alphabet Soup can only teach what a real article says): every other section of
this briefing summarises something that was fetched. The lesson section is the ONLY one whose
subject matter has no feed behind it, which makes it the only place where a model could write from
memory and nothing downstream would notice. A confident wrong sentence about a breaker panel or a
stroke symptom is worse than an empty section.

The production answer is a two-part mechanism: `data/lessons.py` fetches a real English Wikipedia
article FIRST (no article, no lesson), and `summarize._validate_lesson` checks the returned prose
back against that article's text. This file is the machine that keeps both halves honest, because
both fail silently — a fetch guard that stops rejecting bad pages, or a figure guard that stops
matching, produces a page that looks exactly as good as a working one.

  (L1) SOURCES EXIST — every title in `config.LESSON_SEED_ARTICLES` fetches, is not a disambiguation
       page, and clears `LESSON_MIN_SOURCE_CHARS`. The seeds are the FLOOR under the whole section:
       when the model's proposals do not resolve, the day's lesson comes from this list, so a rotted
       title here means a silently missing lesson, not a loud error. (network, keyless)
  (L2) FAIL-CLOSED FETCH — a title that does not exist and a known disambiguation page both return
       None. This is the guard that stops a near-miss article from becoming a "grounded" lesson
       about the wrong subject: every check downstream would pass, since the source WAS real.
  (L3) FIGURE GUARD — prose carrying a dollar amount, a percentage or a year that is absent from the
       article is REJECTED, and the identical prose without it is accepted. A hallucinated figure is
       the highest-consequence output this section can produce and is unguardable anywhere else.
  (L4) DOSAGE GUARD — anything shaped like a drug dosage is rejected outright, whatever the article
       says. "How much to take" is the one question a morning briefing must never answer.
  (L5) LENGTH BOUNDS — a segment below the floor or above the ceiling is rejected. The tiers are what
       the reader's quick/medium/long choice selects; a 600-word "quick" silently breaks that
       contract, in the audio where it is least noticeable.
  (L6) NARRATION MIRROR — the tier names in `tts.compose_lesson_segments`, `config.LESSON_WORD_TARGETS`
       and docs/app.js's SOUP_TIERS all agree. Three copies of one list, two of them in different
       languages: drift here means the phone asks for a clip the build never names, and the reader
       gets the device voice on a day the audio was actually fine.

Runnable NOW (no API key). L1/L2 need network; L3-L6 are offline and instant.
Read-only. Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA (network unreachable).

NEGATIVE CONTROLS (`LESSON_CONTROL=<mode>`, each driving PRODUCTION code red — all three verified
red at authoring time, 2026-08-11):
  blind-figures  -> L3 red. Neutralises the production `_MONEY`/`_YEAR` patterns so an invented
                    figure survives validation.
  allow-dosage   -> L4 red. Neutralises the production `_DOSAGE` pattern.
  no-length-cap  -> L5 red. Raises the production ceiling out of reach.
"""
import os
import re
import sys

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from scripts import config                         # noqa: E402
from scripts import summarize                      # noqa: E402
from scripts import tts                            # noqa: E402
from scripts.data import lessons                   # noqa: E402

# Captured BEFORE any control weakens it. The over-length fixture has to be built from the SHIPPED
# ceiling, or `no-length-cap` would raise the bar and the fixture with it — a control that scales
# with the thing it is trying to break proves nothing (this was the bug on the first run).
SHIPPED_CEILING = config.LESSON_WORD_CEILING

CONTROL = os.environ.get("LESSON_CONTROL", "")
if CONTROL == "blind-figures":
    summarize._MONEY = re.compile(r"(?!x)x")       # matches nothing
    summarize._YEAR = re.compile(r"(?!x)x")
elif CONTROL == "allow-dosage":
    summarize._DOSAGE = re.compile(r"(?!x)x")
elif CONTROL == "no-length-cap":
    config.LESSON_WORD_CEILING = 10_000
if CONTROL:
    print(f"[control] {CONTROL} engaged — production code is deliberately weakened", file=sys.stderr)

FAILURES = []
NETWORK_DEAD = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


class FakeLesson:
    """Stands in for the pydantic model. `_validate_lesson` only ever reads attributes, and building
    the real schema object here would test pydantic rather than the guard."""

    def __init__(self, **kw):
        base = {"title": "How a breaker actually trips", "hook": "Worth knowing.",
                "quick": "word " * 120, "more": "word " * 120, "deep": "word " * 140,
                "takeaway": "Find your panel before you need it."}
        base.update(kw)
        for k, v in base.items():
            setattr(self, k, v)


# ------------------------------------------------------------------ L1 + L2: the fetch boundary
print("\nL1  seed articles all fetch, are not disambiguations, and are long enough")
sample = [t for titles in config.LESSON_SEED_ARTICLES.values() for t in titles]
for title in sample:
    try:
        got = lessons.fetch_article(title)
    except Exception as e:
        NETWORK_DEAD.append(f"{title}: {type(e).__name__}: {e}")
        continue
    check(f"seed {title!r}", bool(got),
          f"{len(got['extract'])} chars" if got else "missing, a stub, or a disambiguation page")

if NETWORK_DEAD and len(NETWORK_DEAD) == len(sample):
    # "Everything failed" is TWO different verdicts and they must not share an exit. A dead
    # network proves nothing and is INFRA. A wall of 429s proves something specific and
    # reproducible: this client is being rate-limited, which on 2026-08-31 meant an unidentified
    # WIKI_UA throttled under burst. Reporting that as "unreachable" is what invites the next
    # reader to shrug it off as flakiness and lose another week of Alphabet Soup.
    # 14-wikipedia-ua.py is the dedicated guard for the User-Agent itself.
    if sum(1 for line in NETWORK_DEAD if "429" in line) > len(sample) // 2:
        print("\nFAIL: en.wikipedia.org RATE-LIMITED every seed fetch (HTTP 429). This is not a "
              "network outage — it is a limiter keyed on this client. Check WIKI_UA in "
              "scripts/data/lessons.py against Wikimedia's User-Agent policy (it needs a real "
              "repo URL and a contact address); 14-wikipedia-ua.py measures exactly this.",
              file=sys.stderr)
        for line in NETWORK_DEAD[:3]:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    print("\nINFRA: en.wikipedia.org is unreachable from here — nothing was proved.",
          file=sys.stderr)
    for line in NETWORK_DEAD[:3]:
        print(f"  {line}", file=sys.stderr)
    sys.exit(3)
for line in NETWORK_DEAD:
    check(f"seed fetch {line.split(':')[0]!r}", False, "transport failure")

print("\nL2  the fetch fails closed on a page that must never become a lesson")
try:
    check("a title that does not exist returns None",
          lessons.fetch_article("Zzqx Not A Real Wikipedia Article 4471") is None)
    check("a disambiguation page returns None", lessons.fetch_article("Mercury") is None)
except Exception as e:
    check("fail-closed fetch", False, f"{type(e).__name__}: {e}")

# ------------------------------------------------------------------ L3-L5: the prose guards
ARTICLE = {"title": "Circuit breaker", "url": "https://en.wikipedia.org/wiki/Circuit_breaker",
           "extract": ("A circuit breaker is an electrical safety device. Early designs appeared in "
                       "1879. A typical residential breaker interrupts at 15 or 20 amperes and "
                       "about 80% of rated load is a common design guideline.")}

print("\nL3  a figure the article does not contain discards the lesson")
check("clean prose is accepted",
      summarize._validate_lesson(FakeLesson(), ARTICLE, "Home, car and repair") is not None)
check("an invented dollar amount is rejected",
      summarize._validate_lesson(FakeLesson(quick="Replacing a panel costs $4,200 " + "word " * 110),
                                 ARTICLE, "Home, car and repair") is None)
check("an invented percentage is rejected",
      summarize._validate_lesson(FakeLesson(deep="About 47% of homes " + "word " * 130),
                                 ARTICLE, "Home, car and repair") is None)
check("an invented year is rejected",
      summarize._validate_lesson(FakeLesson(more="The standard changed in 1994. " + "word " * 115),
                                 ARTICLE, "Home, car and repair") is None)
check("an invented percentage SPELLED OUT is rejected too",
      summarize._validate_lesson(FakeLesson(more="Roughly 47 percent of homes " + "word " * 115),
                                 ARTICLE, "Home, car and repair") is None)
check("a spelled-out percentage the article writes with a % sign survives",
      summarize._validate_lesson(FakeLesson(quick="About 80 percent of rated load is the guideline. "
                                                  + "word " * 112),
                                 ARTICLE, "Home, car and repair") is not None)
check("a figure that IS in the article survives",
      summarize._validate_lesson(FakeLesson(quick="Breakers appeared in 1879 and about 80% of "
                                                  "rated load is the guideline. " + "word " * 110),
                                 ARTICLE, "Home, car and repair") is not None)

print("\nL4  anything shaped like a dosage is discarded whatever the article says")
check("a dosage is rejected",
      summarize._validate_lesson(FakeLesson(quick="Take 200 mg of it. " + "word " * 115),
                                 ARTICLE, "Health and emergencies") is None)

print("\nL5  a segment outside the length bounds is discarded")
check("a too-short segment is rejected",
      summarize._validate_lesson(FakeLesson(quick="Too short."), ARTICLE, "Money mechanics") is None)
check("a too-long segment is rejected",
      summarize._validate_lesson(FakeLesson(deep="word " * (SHIPPED_CEILING + 40)),
                                 ARTICLE, "Money mechanics") is None)

# ------------------------------------------------------------------ L6: the two-language mirror
print("\nL6  the tier list agrees across the build, the narration and the client")
tier_names = [tier for tier, _ in tts.compose_lesson_segments(
    {"title": "t", "hook": "h", "quick": "q", "more": "m", "deep": "d", "takeaway": "k"})]
check("tts segments match config.LESSON_WORD_TARGETS",
      set(tier_names) == set(config.LESSON_WORD_TARGETS), f"tts={tier_names}")
with open(os.path.join(REPO, "docs", "app.js"), encoding="utf-8") as f:
    APP_JS = f.read()
m = re.search(r"const SOUP_TIERS = \{(.+?)\};", APP_JS, re.S)
check("docs/app.js defines SOUP_TIERS", bool(m))
if m:
    body = m.group(1)
    # KEYS are the length names the reader picks (unquoted, before a colon); VALUES are the tier
    # names the build emits (quoted, inside the arrays). Two different vocabularies in one literal —
    # reading them with one pattern is how this check would quietly stop proving anything.
    client_lengths = set(re.findall(r"(\w+)\s*:", body))
    client_tiers = set(re.findall(r'"(\w+)"', body))
    check("client tier names are exactly the build's", client_tiers == set(tier_names),
          f"app.js={sorted(client_tiers)}")
    check("client length names are exactly quick/medium/long",
          client_lengths == {"quick", "medium", "long"}, f"app.js={sorted(client_lengths)}")
check("the client mirrors the outro line",
      tts.OUTRO_TEXT in APP_JS, "SOUP_OUTRO_SPOKEN must equal tts.OUTRO_TEXT")

print("\n" + ("FAIL: " + ", ".join(FAILURES) if FAILURES else "PASS: all lesson assumptions hold"))
sys.exit(1 if FAILURES else 0)
