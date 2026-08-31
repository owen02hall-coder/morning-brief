#!/usr/bin/env bash
set -uo pipefail
if [ "${BRIEFING_SMOKE_ALLOW_DEV:-}" != "true" ]; then
  echo "REFUSED: set BRIEFING_SMOKE_ALLOW_DEV=true to run assumption tests" >&2
  exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS=(
  "04-external-boundary-smoke.py"   # no key — runnable now
  "05-policy-sources.py"            # no key — runnable now; run in CI for runner-IP proof (.gov egress)
  "07-utah-bill-detail.py"          # no key — Utah scrape contract (absolute URL, real bill text)
  "08-prefilter-recall.py"          # no key — prefilter recall + precision + volume
  "09-policy-calendar.py"           # no key, no network — the hardcoded calendar cannot go stale
  "12-narration-mirror.py"          # no key, no network (needs node) — the mp3 script and the
                                    # device-voice script cannot drift apart
  "13-us-news-editorial.py"         # no key needed for C1/C2/C4 — the US section reports events,
                                    # never the partisan contest about them
  "10-lesson-sources.py"            # no key — every seed article resolves and the invented-figure
                                    # guard still bites
  "11-client-pointer.js"            # no key, no network (needs node) — the ONLY check on the
                                    # lesson pointer, which lives entirely in the browser
  "14-wikipedia-ua.py"              # no key — the Wikipedia UA is policy-compliant AND survives a
                                    # burst; controls with the old generic UA
  "01-twelvedata-runner-pull.py"    # needs TWELVEDATA_API_KEY; run in CI for runner-IP proof
  "02-twelvedata-seed-budget.py"    # needs TWELVEDATA_API_KEY
  "03-gemini-structured.py"         # needs GEMINI_API_KEY
  "06-policy-relevance.py"          # needs GEMINI_API_KEY; proves relevance scoring + no invented figures
)
PASS=0; START=$(date +%s)
for t in "${TESTS[@]}"; do
  echo; echo "--- ${t} ---"
  # 150s, not 60s: the model-calling tests (03, 06) set their own 120s client timeout so a hung
  # Gemini call fails with a clean INFRA message. A 60s outer kill would pre-empt that and report a
  # blunt timeout instead of the real reason. This is a hang backstop, not a latency budget.
  # Pick the interpreter from the extension. Until 2026-08-31 this was hardcoded to `python`, which
  # is one reason 11-client-pointer.js was never in the list at all: it simply could not have run.
  case "${t}" in
    *.js) RUNNER=node ;;
    *)    RUNNER=python ;;
  esac
  if timeout 150 "${RUNNER}" "${SCRIPT_DIR}/${t}"; then
    PASS=$((PASS+1))
  else
    rc=$?; [ "$rc" = 124 ] && rc=3   # timeout/hang → INFRASTRUCTURE FAIL
    exit "$rc"
  fi
done
echo; echo "PASS: ${PASS}/${#TESTS[@]} in $(( $(date +%s) - START ))s"
