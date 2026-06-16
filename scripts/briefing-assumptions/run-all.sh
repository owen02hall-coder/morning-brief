#!/usr/bin/env bash
set -uo pipefail
if [ "${BRIEFING_SMOKE_ALLOW_DEV:-}" != "true" ]; then
  echo "REFUSED: set BRIEFING_SMOKE_ALLOW_DEV=true to run assumption tests" >&2
  exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS=(
  "04-external-boundary-smoke.py"   # no key — runnable now
  "01-twelvedata-runner-pull.py"    # needs TWELVEDATA_API_KEY; run in CI for runner-IP proof
  "02-twelvedata-seed-budget.py"    # needs TWELVEDATA_API_KEY
  "03-gemini-structured.py"         # needs GEMINI_API_KEY
)
PASS=0; START=$(date +%s)
for t in "${TESTS[@]}"; do
  echo; echo "--- ${t} ---"
  if timeout 60 python "${SCRIPT_DIR}/${t}"; then
    PASS=$((PASS+1))
  else
    rc=$?; [ "$rc" = 124 ] && rc=3   # timeout/hang → INFRASTRUCTURE FAIL
    exit "$rc"
  fi
done
echo; echo "PASS: ${PASS}/${#TESTS[@]} in $(( $(date +%s) - START ))s"
