# Briefing — Assumption Tests

Pre-flight + regression tests that prove the **load-bearing runtime assumptions** of the
personal morning-briefing project against the real external services it depends on. Text review
can't validate "does a 600-symbol pull work from a GitHub Actions runner" or "does Gemini return
valid structured JSON" — these tests do, by running against the real thing.

These are **assumption tests** (narrow-and-deep, run against real infra), not unit tests
(pure logic vs mocks) and not smoke tests (broad-and-shallow).

## Safety

Every test refuses to run unless `BRIEFING_SMOKE_ALLOW_DEV=true` is set. The tests are read-only
against external services except `03-ntfy-roundtrip.py`, which publishes one message to a
throwaway test topic.

## What each test proves

| Test | Proves | Needs |
|---|---|---|
| `04-external-boundary-smoke.py` | RSS feeds parse + enough fresh items in 72h + ≥1 world feed alive; Wikipedia S&P500/NDX tables parse to ~500/~100 via header-matched column; symbol normalization output is stable | nothing (runnable now); `feedparser`, `pandas`, `lxml` |
| `01-twelvedata-runner-pull.py` | ~600-constituent + index (SPX/NDX/VIX/10Y) daily pull succeeds **from a runner IP** within ~650 credits; class-share symbols resolve | `TWELVEDATA_API_KEY`; **run in CI** for the runner-IP proof |
| `02-twelvedata-seed-budget.py` | a 250-day seed doesn't multiply credits; full ~600 seed fits in one 800/day window; whether seed + same-day daily pull needs to wait for the 00:00 UTC reset | `TWELVEDATA_API_KEY` |
| `03-gemini-structured.py` | which `google-genai` config shape works on the pinned SDK; `resp.parsed` returns a valid schema object (not None) | `GEMINI_API_KEY`; `google-genai`, `pydantic` |

The biggest risk (test 1, runner-IP) is only truly closed when test 1 runs **inside a GitHub
Actions `workflow_dispatch` job** — a local pass proves the API contract but not the runner-IP case
(that is exactly what killed yfinance).

## How to run

```bash
# all tests (halts on first failure)
BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh

# a single test
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/03-ntfy-roundtrip.py
```

Key-gated tests also need their secret in the environment:
`TWELVEDATA_API_KEY` (test 1), `GEMINI_API_KEY` (test 2), and `NTFY_TOPIC` (test 3).

## Exit codes

- `0` PASS — all assertions held
- `1` FAIL — at least one assertion failed (a real regression / wrong assumption)
- `2` REFUSED — safety gate `BRIEFING_SMOKE_ALLOW_DEV` not set
- `3` INFRASTRUCTURE FAIL — couldn't run (network down, missing key/dep, hang/timeout)

## Fingerprints

On PASS, tests that depend on external environment facts write a `<NN>-<name>.fingerprint.json`
recording the assumption-relevant facts (e.g. resolved model id, credit cost, feed set). A
mismatch on a later run means the environment drifted — re-validate before trusting the green.

## Gate placement

- **Pre-implementation:** run before `/implement`. All runnable tests must PASS; key-gated tests
  must PASS once keys exist.
- **Runner-IP proof:** run `01-twelvedata-pull.py` inside a `workflow_dispatch` GitHub Actions job
  (not just locally) — local success does not prove the runner-IP case.
- **Post-ship regression:** re-run after each slice; any FAIL = regression.
