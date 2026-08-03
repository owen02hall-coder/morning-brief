# Briefing — Assumption Tests

Pre-flight + regression tests that prove the **load-bearing runtime assumptions** of the
personal morning-briefing project against the real external services it depends on. Text review
can't validate "does a 600-symbol pull work from a GitHub Actions runner" or "does Gemini return
valid structured JSON" — these tests do, by running against the real thing.

These are **assumption tests** (narrow-and-deep, run against real infra), not unit tests
(pure logic vs mocks) and not smoke tests (broad-and-shallow).

## Safety

Every test refuses to run unless `BRIEFING_SMOKE_ALLOW_DEV=true` is set. All four tests are
read-only against external services (`03-gemini-structured.py` sends one prompt to Gemini but
publishes/writes nothing anywhere).

## What each test proves

| Test | Proves | Needs |
|---|---|---|
| `04-external-boundary-smoke.py` | RSS feeds parse + enough fresh items in 72h + ≥1 world feed alive; Wikipedia S&P500/NDX tables parse to ~500/~100 via header-matched column; symbol normalization output is stable | nothing (runnable now); `feedparser`, `pandas`, `lxml` |
| `05-policy-sources.py` | (planned "policy that affects me" section) Federal Register API answers one multi-agency, type-filtered, date-windowed query with all fields the item format needs; every result URL is on federalregister.gov so the `.gov` guard is code-enforceable; volume stays bounded; Freddie Mac PMMS CSV parses and is fresh; the Utah Legislature passed-bills page is scrapable to (number, title, signed-status) — Utah publishes no JSON API | nothing (runnable now) |
| `06-policy-relevance.py` | (planned policy section) the model, given a LIFE_PROFILE and a REAL candidate set, selects only documents that create a number/deadline/obligation; cites only fetched federalregister.gov URLs; fills a non-empty `effect` on every item; **rejects three seeded real-but-irrelevant decoys** (OSHA benzene, mine ventilation, blacksmith shops) so a model that just returns the first N cannot pass; invents no dollar amount or percentage absent from the source | `GEMINI_API_KEY`; `google-genai`, `pydantic` |
| `01-twelvedata-runner-pull.py` | ~600-constituent + index (SPX/NDX/VIX/10Y) daily pull succeeds **from a runner IP** within ~650 credits; class-share symbols resolve | `TWELVEDATA_API_KEY`; **run in CI** for the runner-IP proof |
| `02-twelvedata-seed-budget.py` | a 250-day seed doesn't multiply credits; full ~600 seed fits in one 800/day window; whether seed + same-day daily pull needs to wait for the 00:00 UTC reset | `TWELVEDATA_API_KEY` |
| `03-gemini-structured.py` | which `google-genai` config shape works on the pinned SDK; `resp.parsed` returns a valid schema object (not None) | `GEMINI_API_KEY`; `google-genai`, `pydantic` |

The biggest risk (test 1, runner-IP) is only truly closed when test 1 runs **inside a GitHub
Actions `workflow_dispatch` job** — a local pass proves the API contract but not the runner-IP case
(that is exactly what killed yfinance). **The same caveat applies to test 5**: it passed from a home
connection on 2026-08-03, which proves the API contracts but NOT that `.gov` hosts and
`le.utah.gov` answer a GitHub runner's egress IP. Until it runs green in CI, treat test 5 as
"contract proven, egress unproven".

### Sources deliberately NOT used (probed 2026-08-03, all dead or key-gated)

`Congress.gov API` (403 without an api.data.gov key) · `CFPB newsroom feed` (403 to bot and browser
UAs) · `FHFA / IRS / HUD RSS` (404 at every documented-looking path) · `Utah Tax Commission RSS`
(200 but zero entries) · `propertytax.utah.gov` (JS-rendered; no static Truth-in-Taxation text) ·
`Utah Housing Corp feed` (403/503) · `le.utah.gov` bulk "Bill Data" (an iframe wrapper, not a
dataset). CFPB/FHFA/IRS/HUD rulemaking is covered by the Federal Register query anyway — which is
why that API is the backbone rather than a collection of per-agency feeds. Do not re-add any of
these without re-probing first.

## How to run

```bash
# all tests (halts on first failure)
BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh

# a single test
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/03-gemini-structured.py
```

Key-gated tests also need their secret in the environment:
`TWELVEDATA_API_KEY` (tests 1 and 2) and `GEMINI_API_KEY` (test 3). Test 4 needs no key but
does need `pandas` + `lxml` installed (not in requirements.txt — dev-only deps). Test 5 needs
neither a key nor extra deps.

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
- **Runner-IP proof:** run `01-twelvedata-runner-pull.py` inside a `workflow_dispatch` GitHub
  Actions job (not just locally) — local success does not prove the runner-IP case.
- **Post-ship regression:** re-run after each slice; any FAIL = regression.
