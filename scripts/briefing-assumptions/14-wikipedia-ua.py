"""W1-W4: the Wikipedia User-Agent is policy-compliant, REACHES every caller, and survives a burst.

WHY THIS TEST EXISTS. Owen's Alphabet Soup went dark for days at the end of August 2026 and the only
signal was a LOW-priority "degraded sections: alphabet soup" push that named no cause. The cause was
one string: WIKI_UA ended in a bare "https://github.com/" — a hostname with no repo path and no
contact address, which Wikimedia's User-Agent policy treats as unidentified.

The failure mode is what made it hard to see. It is NOT a block, it is a rate-limit CLASS. At a slow
trickle the generic UA is let through (a one-off manual fetch looks fine, which is exactly how the
first diagnosis on 2026-08-31 briefly went wrong), but the lesson leg fetches candidates in a tight
burst, and under burst Wikimedia throttled the generic UA to 100%. Measured that day, 12 distinct
titles, alternating order, no sleeps: generic UA 429 on 12/12, compliant UA 200 on 12/12. Because
`retry.py`'s process-global budget was sized for a documented 12-request policy/mortgage surface that
never counted this leg, the first two candidates spent the whole budget and the other fourteen ran
with no retries at all.

Silent AND able to recur — a future edit could re-generalise the string and nothing would go red —
which is this project's two-part gate for enforcing a bug class with a machine instead of a note.

  W1  SHAPE — the UA carries a repo URL with a real path and a contact address. Offline, so it fails
      in CI even on a day Wikipedia is unreachable. This is the half that pins the actual regression.
  W2  REACH — every production module that actually FETCHES Wikipedia sends config.WIKI_UA. Offline.
      Added 2026-09-01, because W1 reads ONE string and therefore stayed green through a second
      instance of the same bug: the 08-31 fix reached data/lessons.py and left data/constituents.py
      — breadth's constituent scrape — sending the generic config.USER_AGENT to the same host. A
      correct constant that no caller reaches is not a fix, and nothing here could tell.
  W3  BURST — the shipped UA really survives a rapid burst of distinct titles. Network. This is the
      half that would catch Wikimedia tightening policy again in a way W1's shape rule cannot predict.
  W4  CONTROL — the deliberately-generic UA still gets throttled under the same burst. Without this,
      W3 passes trivially the day Wikimedia stops rate-limiting anyone at all, and the test would go
      on reporting PASS while proving nothing.

W4 is a measurement of someone else's live policy, not of our code, so it is reported and NOT failed
on: if Wikimedia ever stops throttling generic UAs, W3 is what still matters and W4 turning yellow is
information, not a broken build.

  BRIEFING_SMOKE_ALLOW_DEV=true  required, like every test here.
"""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from scripts import config                         # noqa: E402
from scripts.data import lessons                   # noqa: E402

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{' — ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(label)


# The UA this test measures the SHIPPED one against. Kept verbatim as it stood when the outage
# happened, so W4 controls with the real thing rather than an invented near-miss.
GENERIC_UA = "morning-briefing/1.0 (personal daily briefing; https://github.com/) python-urllib"

# Distinct titles, no repeats: a burst of the SAME title can be served from cache and would not
# exercise the limiter at all.
BURST_TITLES = ["Groupthink", "Propaganda", "Sunk cost", "Negotiation", "Framing effect",
                "Loss aversion", "Anchoring effect", "Survivorship bias"]


def burst(ua, titles):
    """Fire `titles` back-to-back with no sleep and return the list of status codes."""
    codes = []
    for t in titles:
        params = {"action": "query", "format": "json", "formatversion": 2,
                  "redirects": 1, "prop": "extracts", "explaintext": 1, "titles": t}
        req = urllib.request.Request(
            config.WIKI_API + "?" + urllib.parse.urlencode(params),
            headers={"User-Agent": ua, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=config.WIKI_TIMEOUT) as r:
                codes.append(r.status)
        except urllib.error.HTTPError as e:
            codes.append(e.code)
        except Exception as e:                      # transport death: not a status, not a verdict
            codes.append(type(e).__name__)
    return codes


# ---------------------------------------------------------------- W1: shape (offline, no network)
print("\nW1  the shipped User-Agent identifies this client the way Wikimedia's policy asks")
ua = config.WIKI_UA
check("names a contact address", "@" in ua, ua)
check("carries a repo URL with a path, not a bare host",
      "https://github.com/" in ua and ua.split("https://github.com/", 1)[1][:1] not in ("", " ", ")"),
      "a bare https://github.com/ is what Wikimedia read as unidentified")
check("is not the generic UA that caused the 2026-08-31 outage", ua != GENERIC_UA)

# ---------------------------------------------------------------- W2: reach (offline, no network)
print("")
print("W2  every production module that fetches Wikipedia sends config.WIKI_UA")
WIKI_MARKERS = ("wikipedia.org", "WIKI_API", "_WIKI_URL")
# A mention is not a fetch. retry.py names en.wikipedia.org in a comment about Retry-After and
# builds no request at all, so requiring a marker AND request construction keeps this guard off
# files it has no business grading — which is how a guard earns the right to stay un-muted.
FETCH_MARKERS = ("urllib.request.Request(", "urlopen(")

callers = []
for _d in (os.path.join(REPO, "scripts", "data"), os.path.join(REPO, "scripts", "breadth")):
    for _fn in sorted(os.listdir(_d)):
        if not _fn.endswith(".py") or _fn == "__init__.py":
            continue
        with open(os.path.join(_d, _fn), encoding="utf-8") as _fh:
            _src = _fh.read()
        if any(m in _src for m in WIKI_MARKERS) and any(m in _src for m in FETCH_MARKERS):
            callers.append((f"scripts/{os.path.basename(_d)}/{_fn}", "config.WIKI_UA" in _src))

# Fail closed on an empty result: two modules fetch Wikipedia today, so "no callers found" means the
# markers rotted and this check is grading nothing — never that the risk went away.
check("the detector still finds the Wikipedia callers", len(callers) >= 2, f"found {len(callers)}")
for _path, _uses in callers:
    check(f"{_path} sends config.WIKI_UA", _uses,
          "" if _uses else "fetches Wikipedia with some OTHER User-Agent — the 08-31 bug, again")

# ---------------------------------------------------------------- W3 + W4: the live burst
print(f"\nW3  the shipped UA survives a burst of {len(BURST_TITLES)} distinct titles, no sleeps")
shipped = burst(ua, BURST_TITLES)
ok200 = sum(1 for c in shipped if c == 200)
n429 = sum(1 for c in shipped if c == 429)
dead = [c for c in shipped if not isinstance(c, int)]

if len(dead) == len(shipped):
    # Every request died at the transport layer — that is an unreachable network, which proves
    # nothing either way. Exit 3 is this suite's INFRA code and is distinct from a red test.
    print("\nINFRA: en.wikipedia.org is unreachable from here — nothing was proved.", file=sys.stderr)
    print(f"  {dead[0]}", file=sys.stderr)
    sys.exit(3)

check(f"shipped UA is not throttled ({ok200}/{len(shipped)} OK, {n429} x 429)",
      n429 == 0, f"codes={shipped}")

print("\nW4  control: the old generic UA is still throttled under the same burst")
control = burst(GENERIC_UA, BURST_TITLES)
c429 = sum(1 for c in control if c == 429)
if c429:
    print(f"  PASS  generic UA throttled {c429}/{len(control)} — W3 above is a real measurement")
else:
    print(f"  NOTE  generic UA was NOT throttled this run (codes={control}). Wikimedia may have "
          f"relaxed its limiter, or this host is under a quota the runner is not. W3 stands on its "
          f"own; this line is information, not a failure.")

print("\n" + ("FAIL: " + ", ".join(FAILURES) if FAILURES
              else "PASS: the Wikipedia User-Agent is compliant and survives a burst"))
sys.exit(1 if FAILURES else 0)
