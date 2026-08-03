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
  if timeout 150 python "${SCRIPT_DIR}/${t}"; then
    PASS=$((PASS+1))
  else
    rc=$?; [ "$rc" = 124 ] && rc=3   # timeout/hang → INFRASTRUCTURE FAIL
    exit "$rc"
  fi
done
echo; echo "PASS: ${PASS}/${#TESTS[@]} in $(( $(date +%s) - START ))s"
