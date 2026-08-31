#!/usr/bin/env python3
"""ASSUMPTION 15: the data-smoke alarm says WHY the run is red, and says it correctly.

WHY THIS TEST EXISTS. On 2026-08-31 the weekly Data Smoke run went red and paged, at high priority,
"A DATA SOURCE went red from the runner: external-boundary. Something is broken or has drifted
upstream." Every data source was healthy. 04 had exited 3 (INFRA) on `import pandas`, a package that
is deliberately not a dependency of this project, so the test never made an assertion at all. The
alert read only the step OUTCOME, and an outcome of "failure" collapses exit 1 (the assertion went
red), exit 2 (refused: no key, no dev gate) and exit 3 (infra: missing package, dead host, hang)
into one indistinguishable verdict.

That is the failure mode this whole workflow was rebuilt on 08-31 to prevent, one level up. The
argument there was that a pager which cannot tell a dead source from a model having an opinion is a
pager you learn to swipe away. A pager that cannot tell a dead source from a test that never ran is
the same defect, and it is worse in one specific way: it does not just cry wolf, it points at the
wrong animal. The morning it fired, it sent the reader looking upstream for a break that was not
there.

Silent AND able to recur, which is this project's two-part gate for a machine instead of a note: the
alert has no output anyone checks, so a misclassification looks exactly like a correct one, and any
future step added without its `rc` capture, or any edit to the `cls` dispatch, re-opens it.

  A1  The alarm still exists and still fires only on a red run.
  A2  Every test step records its exit code, and every recorded code reaches the alert as an env
      var. A step whose rc is captured but never read is the "guard with no trigger" shape again.
  A3  The shipped classifier, executed, sorts the cases correctly - most importantly that exit 3
      pages as a HARNESS fault and never as an upstream drift.

A3 runs the REAL script lifted out of the workflow, not a copy. A copy is what let 04's constituent
parse drift away from production's for weeks.

Offline, no key, no network, stdlib only (this test of all tests must not import a package CI does
not have). Needs `bash`, which every ubuntu runner has.
Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
NEGATIVE CONTROL: ALERT_CASE_OVERRIDE=<name of a case> inverts that case's expectation, so you can
prove A3 is really grading the script.
"""
import os
import re
import subprocess
import sys
import tempfile

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WF = os.path.join(REPO, ".github", "workflows", "data-smoke.yml")

FAILURES = []


def check(label, ok, detail=""):
    """detail is the FAILURE explanation, so it prints only when the check is red."""
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'' if ok or not detail else ' — ' + detail}")
    if not ok:
        FAILURES.append(label)


try:
    SRC = open(WF, encoding="utf-8").read()
except OSError as e:
    print(f"INFRA: cannot read {WF} ({e})", file=sys.stderr)
    sys.exit(3)

# ------------------------------------------------------------------ A1: the alarm exists and is armed
print("\nA1  the alarm still exists, and still fires only on a red run")
alert_name = "Alert on a red data-smoke run"
check("the alert step is still in the workflow", alert_name in SRC,
      "no step by that name — this job would go red and page NOBODY")
check("it is gated on failure() || cancelled()", "if: failure() || cancelled()" in SRC,
      "a timeout kill is a CANCELLATION; failure() alone misses the slowest failure mode")

# ------------------------------------------------------------------ A2: every step's rc is captured AND read
print("\nA2  every test step records an exit code, and the alert reads every one it records")
# `id: foo` on a step that also writes rc=$? into GITHUB_OUTPUT.
ids_writing_rc = []
for block in re.split(r"\n      - ", SRC):
    m = re.search(r"^\s*id:\s*(\S+)", block, re.M)
    if m and "GITHUB_OUTPUT" in block and "rc=$rc" in block:
        ids_writing_rc.append(m.group(1))

check("test steps capture their exit code", len(ids_writing_rc) >= 12,
      f"found {len(ids_writing_rc)} — every assertion step needs `rc=0; cmd || rc=$?`")

unread = [i for i in ids_writing_rc if f"steps.{i}.outputs.rc" not in SRC]
check("every captured exit code is wired into the alert's env", not unread,
      "captured but never read: " + ", ".join(unread) if unread else "")

# The reverse direction: a step whose OUTCOME the alert reads but whose rc it does not can only ever
# be classified by the old, ambiguous rule.
outcome_ids = set(re.findall(r"steps\.(\w+)\.outcome", SRC))
rc_ids = set(re.findall(r"steps\.(\w+)\.outputs\.rc", SRC))
missing_rc = sorted(outcome_ids - rc_ids)
check("no step is graded by outcome alone", not missing_rc,
      "outcome read but no rc: " + ", ".join(missing_rc) if missing_rc else "")

# ------------------------------------------------------------------ A3: run the shipped classifier
print("\nA3  the shipped classifier sorts a red run into the right class")

# Lift the alert's `run:` block out of the YAML by indentation. Deliberately NOT via a YAML parser:
# PyYAML is not in requirements.txt, and importing a package CI does not have is the exact bug this
# file exists to keep from being mis-paged ever again.
lines = SRC.split("\n")
start = next((i for i, ln in enumerate(lines) if alert_name in ln and ln.lstrip().startswith("- name:")), None)
if start is None:
    print("FAIL: 15-alert-classification — the alert step is gone; A3 cannot run", file=sys.stderr)
    sys.exit(1)
run_at = next((i for i in range(start, len(lines)) if lines[i].strip() == "run: |"), None)
if run_at is None:
    print("INFRA: could not find the alert's `run: |` block", file=sys.stderr)
    sys.exit(3)
body = []
for ln in lines[run_at + 1:]:
    if ln.strip() and not ln.startswith(" " * 10):
        break
    body.append(ln[10:] if len(ln) >= 10 else ln)
script = "\n".join(body).rstrip()
if len(script.splitlines()) < 20:
    print(f"INFRA: extracted only {len(script.splitlines())} lines of alert script — extraction "
          f"drifted, and a short script would make A3 pass vacuously", file=sys.stderr)
    sys.exit(3)

STEPS = ["SPINE", "BOUNDARY", "POLICY_SOURCES", "UTAH_DETAIL", "PREFILTER", "CALENDAR",
         "LESSON_SOURCES", "WIKIPEDIA_UA", "CLIENT_POINTER", "NARRATION", "EDITORIAL", "RELEVANCE",
         "ALERT_CLASS"]

fd, path = tempfile.mkstemp(suffix=".sh")
# curl is stubbed: this test asserts what the alert SAYS, and must never send a push.
os.write(fd, ("curl() { return 0; }\n" + script).encode("utf-8"))
os.close(fd)


def fire(**over):
    env = dict(os.environ, NTFY_TOPIC="test-topic", RUN_URL="http://example/run")
    for k in STEPS:
        env[k], env[k + "_RC"] = "success", "0"
    env.update(over)
    try:
        r = subprocess.run(["bash", "-e", path], capture_output=True, text=True, env=env, timeout=60)
    except FileNotFoundError:
        print("INFRA: bash not found — cannot execute the alert script", file=sys.stderr)
        sys.exit(3)
    return r.stdout.strip()


CASES = [
    ("infra-not-drift", dict(BOUNDARY="failure", BOUNDARY_RC="3"),
     ["COULD NOT RUN", "external-boundary", "HARNESS"], ["drifted upstream"]),
    ("real-source-failure", dict(BOUNDARY="failure", BOUNDARY_RC="1"),
     ["Data smoke FAILED", "DATA SOURCE went red"], ["COULD NOT RUN"]),
    ("refused-is-harness", dict(RELEVANCE="failure", RELEVANCE_RC="2"),
     ["COULD NOT RUN", "policy-relevance"], ["flapped"]),
    ("judgment-stays-low", dict(EDITORIAL="failure", EDITORIAL_RC="1"),
     ["[low]", "judgment test flapped"], ["COULD NOT RUN", "DATA SOURCE"]),
    ("harness-leads-but-source-still-named",
     dict(BOUNDARY="failure", BOUNDARY_RC="3", SPINE="failure", SPINE_RC="1"),
     ["COULD NOT RUN", "a data source IS red", "market-spine"], []),
    ("unset-rc-degrades-safely", dict(BOUNDARY="failure", BOUNDARY_RC=""),
     ["DATA SOURCE went red"], ["COULD NOT RUN"]),
    ("red-with-no-failed-step-still-pages", dict(),
     ["no known step reported failure", "[high]"], []),
    ("cancelled-is-not-broken", dict(BOUNDARY="cancelled", BOUNDARY_RC=""),
     ["no known step reported failure"], ["external-boundary"]),
]

invert = os.environ.get("ALERT_CASE_OVERRIDE")
for name, over, must, must_not in CASES:
    out = fire(**over)
    if name == invert:
        must, must_not = must_not, must
    bad = [f"missing {m!r}" for m in must if m not in out]
    bad += [f"unwanted {m!r}" for m in must_not if m in out]
    check(name, not bad, "; ".join(bad) if bad else "")
os.unlink(path)

if FAILURES:
    print("\nFAIL: 15-alert-classification — " + ", ".join(FAILURES), file=sys.stderr)
    sys.exit(1)
print(f"\nPASS: 15-alert-classification — A1,A2,A3 ({len(ids_writing_rc)} steps capture an exit "
      f"code, {len(CASES)} classification cases correct)")
