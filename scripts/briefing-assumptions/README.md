# Briefing — Assumption Tests

Pre-flight + regression tests that prove the **load-bearing runtime assumptions** of the
personal morning-briefing project against the real external services it depends on. Text review
can't validate "does a 600-symbol pull work from a GitHub Actions runner" or "does Gemini return
valid structured JSON" — these tests do, by running against the real thing.

These are **assumption tests** (narrow-and-deep, run against real infra), not unit tests
(pure logic vs mocks) and not smoke tests (broad-and-shallow).

## Safety

Every test refuses to run unless `BRIEFING_SMOKE_ALLOW_DEV=true` is set. Every test is read-only
against external services: `03-gemini-structured.py` sends one prompt to Gemini and
`06-policy-relevance.py` sends three, but neither publishes or writes anything anywhere outside this
directory's fingerprint files.

## What each test proves

| Test | Proves | Needs |
|---|---|---|
| `04-external-boundary-smoke.py` | RSS feeds parse + enough fresh items in 72h + ≥1 world feed alive; Wikipedia S&P500/NDX tables parse to ~500/~100 via header-matched column; symbol normalization output is stable | nothing (runnable now); `feedparser`, `pandas`, `lxml` |
| `05-policy-sources.py` | the Federal Register API answers one multi-agency, type-filtered, date-windowed query with all fields the item format needs; every result URL is on federalregister.gov so the `.gov` guard is code-enforceable; volume stays bounded; Freddie Mac PMMS CSV parses and is fresh; the Utah Legislature passed-bills page is scrapable to (number, title, signed-status) — Utah publishes no JSON API. The FR query shape (`FR_API`/`FR_AGENCIES`/`FR_FIELDS`/`FR_WINDOW_DAYS`/`FR_PER_PAGE`) is IMPORTED from `scripts/config.py`, so the gate follows what production actually sends | nothing (runnable now) |
| `07-utah-bill-detail.py` | 3 rows sampled from the LIVE passed-bills page (≥1 HB, ≥1 SB) resolve via `urljoin` to absolute `https://le.utah.gov/` URLs (A1); each bill's detail page returns 200 under the exact UA production sends (A2); **production's own** `policy._fetch_bill_detail` yields ≥ the floor (A3 — now 100, not 200: the shortest real bill summary measured across 52 signed bills was 123 chars, so 200 would have gone red on a short-but-good bill); body size and per-fetch wall time sit under stated ceilings (A4); and **A5 — the assertion this file now exists for: the exact `summarize.POLICY_PROMPT_TEXT_CHARS` slice that REACHES THE MODEL must read like a bill (fail-closed) and must contain no navigation marker (fail-loud).** The earlier version of this test passed while the model was receiving ~500 characters of site navigation, because it asserted against the full 4,700-character stripped page instead of the slice that actually ships — that is why A5 exists. Title tokens are recorded in the fingerprint but deliberately NOT asserted (3 of 20 measured bills paraphrase their own title, so a hard check there would be a flaky gate). The test imports production (`policy.POLICY_UA`, `_fetch_bill_detail`, `_normalize_utah`, `summarize._policy_docs_block`) rather than holding local copies | nothing (runnable now) |
| `08-prefilter-recall.py` | the LIFE_PROFILE keyword prefilter — which sits UPSTREAM of the only component 06 proves — retains both documents the live model selected (pinned by `document_number` so the fixture cannot age out) and 4 known-relevant Utah bills on title alone; admits **none** of 4 decoys; admits ≤18% of the ~491 live signed Utah bills (an over-broad prefilter turns `MAX_POLICY_ITEMS` truncation into a lottery); and the word-boundary matcher handles `rent`/*current*, `mortgage`/"mortgages", and `401(k)`. Imports `config.LIFE_PROFILE_KEYWORDS`, so broadening the shipped list moves this gate with it | nothing (runnable now) |
| `06-policy-relevance.py` | G1–G8: the model, given the production `LIFE_PROFILE` and a real candidate set, selects only documents that create a number/deadline/obligation; every citation joins back through the production `_norm_url` to a fetched document on one of the two primary `.gov` hosts; every item has a non-empty `effect`; it **rejects three seeded real-but-irrelevant decoys** (OSHA benzene, mine ventilation, blacksmith shops) so a model that just returns the first N cannot pass; invents no dollar amount or percentage absent from the source; writes no hedge word in a settled-law `effect`; two live tilde-bearing Utah bills round-trip; and two extra single-document probes close the "1-of-1 vs best-2-of-24" seam production actually operates in. Everything production-shaped is IMPORTED (`policy._federal_candidates`, `summarize.POLICY_SYSTEM`, `PolicySection`, `_MONEY`, `_norm_url`, `_policy_docs_block`) — a rename goes red at import instead of quietly proving nothing. The one deliberate exception is the host allowlist, asserted against a local tuple so widening `_ALLOWED_HOSTS` cannot silently widen this gate | `GEMINI_API_KEY`; `google-genai`, `pydantic` |
| `01-twelvedata-runner-pull.py` | ~600-constituent + index (SPX/NDX/VIX/10Y) daily pull succeeds **from a runner IP** within ~650 credits; class-share symbols resolve | `TWELVEDATA_API_KEY`; **run in CI** for the runner-IP proof |
| `02-twelvedata-seed-budget.py` | a 250-day seed doesn't multiply credits; full ~600 seed fits in one 800/day window; whether seed + same-day daily pull needs to wait for the 00:00 UTC reset | `TWELVEDATA_API_KEY` |
| `03-gemini-structured.py` | which `google-genai` config shape works on the pinned SDK; `resp.parsed` returns a valid schema object (not None) | `GEMINI_API_KEY`; `google-genai`, `pydantic` |

The biggest risk (test 1, runner-IP) is only truly closed when test 1 runs **inside a GitHub
Actions `workflow_dispatch` job** — a local pass proves the API contract but not the runner-IP case
(that is exactly what killed yfinance). That caveat still stands for tests 1 and 2, which are
key-gated and are NOT in any workflow.

It no longer applies to the policy tests. `.github/workflows/data-smoke.yml` runs **05, 07, 08 and
06 from a GitHub runner on a weekly schedule** (`0 16 * * 1`) as well as on dispatch, each as its own
`if: always()` step so one dead leg cannot mask the others, and a red **or cancelled** run pushes a
high-priority ntfy. Runner egress to `federalregister.gov`, `freddiemac.com` and `le.utah.gov` is
therefore re-proven every Monday rather than assumed from one home-connection pass — and the answer
arrives as a push, not as an unread Actions email. What retires the old "contract proven, egress
unproven" caveat is that trigger: the caveat described a workflow nobody ran, which is the same
condition that let Nasdaq-100 breadth stay dead for 22 days with a working guard in place.

### Sources deliberately NOT used (probed 2026-08-03, all dead or key-gated)

`Congress.gov API` (403 without an api.data.gov key) · `CFPB newsroom feed` (403 to bot and browser
UAs) · `FHFA / IRS / HUD RSS` (404 at every documented-looking path) · `Utah Tax Commission RSS`
(200 but zero entries) · `propertytax.utah.gov` (JS-rendered; no static Truth-in-Taxation text) ·
`Utah Housing Corp feed` (403/503) · `le.utah.gov` bulk "Bill Data" (an iframe wrapper, not a
dataset). CFPB/FHFA/IRS/HUD rulemaking is covered by the Federal Register query anyway — which is
why that API is the backbone rather than a collection of per-agency feeds. Do not re-add any of
these without re-probing first.

## Negative controls

A test that has never been forced red proves nothing — a green run and a vacuous run look identical.
Each test therefore documents an env var that drives a specific assertion into failure, and each
control records whether it has actually been exercised.

| Env var | Test | Effect |
| --- | --- | --- |
| (unset `BRIEFING_SMOKE_ALLOW_DEV`) | all | REFUSED, exit 2 |
| `SEED_BUDGET_OVERRIDE=<tiny>` | 02 | forces A2 red |
| `FRESH_HOURS_OVERRIDE=0` | 04 | forces A1 (feed freshness) red |
| `EXPECT_SP500_OVERRIDE=<absurd>` | 04 | forces A2 (constituent count) red |
| `FR_SINCE_OVERRIDE=2099-01-01` | 05 | forces P1 red — a valid query with zero results |
| `PMMS_MAX_AGE_DAYS_OVERRIDE=0` | 05 | forces P4 red — nothing is ever that fresh |
| `UTAH_MIN_PASSED_OVERRIDE=99999` | 05 | forces P5 red |
| `UTAH_DETAIL_MIN_CHARS_OVERRIDE=999999` | 07 | forces A3 red — the extracted bill text can never be that long |
| `UTAH_CHROME_CONTROL=true` | 07 | forces A5 red — swaps in the PRE-FIX extraction (the whole bill page stripped whole), so site navigation lands inside the model-visible slice. 07's docstring calls this the regression the file stands in front of: run it after any change to `policy._fetch_bill_detail` and confirm it is still red, or A5 has quietly stopped measuring anything. Does not rewrite the fingerprint |
| `PREFILTER_KEYWORDS_OVERRIDE=zzz` | 08 | forces R1 + R2 red — neither pinned federal document nor any Utah title survives |
| `PREFILTER_KEYWORDS_OVERRIDE="amendment,income tax,property tax,housing,401(k),direct loan,health plan"` | 08 | forces P1 + V1 red — `amendment` admits the appropriations decoy AND 383/491 (78.0%) of all signed Utah bills, far over the 18% ceiling |
| `PREFILTER_MAX_VOLUME_PCT=<n>` | 08 | moves V1's volume ceiling (default 18) |
| `POLICY_PROBE_DOC_OVERRIDE=<irrelevant document_number>` | 06 | *should* force G8's positive probe red — **authored 2026-08-03, not yet exercised** (needs a key) |
| `MODEL_ID=<weaker model>` | 06 | the honest way to ask whether the gate measures the model or the prompt — **not yet exercised** |

The policy-test controls (05, 07, 08) were each verified to actually go red on 2026-08-03; 02's and
04's date from their own authoring; 06's are written down but unexercised, because that file cannot
be run to green without a Gemini key. Exercise them on a CI dispatch and record the result here.

Two entries that look like controls and are not:

- **`FR_PER_PAGE_OVERRIDE=5` (test 05) does NOT go red.** It forces the API to truncate and then
  asserts (P3b) that `count` still reports the FULL total, i.e. `count > len(results)`. That is a
  property, not a failure — and it is the property every count-based volume bound depends on:
  production requests `per_page=config.FR_PER_PAGE` (100) and the API drops everything past it
  SILENTLY, so a bound on `count` can only see truncation if `count` keeps counting past the page.
  Set the override BELOW the live volume (~21 documents / 45 days) or the assertion simply does not
  engage — the run says so on stderr. A `FR_PER_PAGE_OVERRIDE` run deliberately does **not** rewrite
  the fingerprint, since its numbers are truncated on purpose.
- **`FR_AGENCY_OVERRIDE=not-an-agency` (test 05) is a discovered property.** A misspelled agency slug
  returns HTTP 400, not an empty result set, so a typo fails LOUDLY (exit 3 INFRA) instead of quietly
  dropping that agency's coverage. That good failure mode is why P1's empty-result control has to be
  driven by the date window instead.

## How to run

```bash
# all tests (halts on first failure)
BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh

# a single test
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/03-gemini-structured.py
```

Key-gated tests also need their secret in the environment: `TWELVEDATA_API_KEY` (tests 1 and 2) and
`GEMINI_API_KEY` (tests 3 and 6). Test 4 needs no key but does need `pandas` + `lxml` installed (not
in requirements.txt — dev-only deps). Tests 5, 7 and 8 need neither a key nor extra deps.

Tests 5, 6 and 8 import from `scripts/` (`from scripts import config`, and 6 imports the production
policy surface). Running them by bare path from a checkout works — each inserts the repo root on
`sys.path` — but `PYTHONPATH=<repo root>` is the explicit route, and it is what `data-smoke.yml`
sets. `python -m` cannot address these files at all: the names start with digits and contain
hyphens, and the directory has no `__init__.py`.

```bash
PYTHONPATH=. BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/05-policy-sources.py
```

`run-all.sh` halts on the first non-zero exit, and tests 1 and 2 exit 3 without
`TWELVEDATA_API_KEY` — so to gate the policy work, run 05/07/08/06 individually or dispatch the
**Data Smoke** workflow, whose steps are independent.

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
  Actions job (not just locally) — local success does not prove the runner-IP case. Tests 05, 06,
  07 and 08 need no manual step: `data-smoke.yml` runs them from a runner every Monday.
- **Post-ship regression:** re-run after each slice; any FAIL = regression. For the policy legs the
  weekly Data Smoke run is that regression net, and it pages on red rather than emailing.
- **After touching any data source or the policy config:** dispatch Data Smoke. Editing
  `LIFE_PROFILE_KEYWORDS` moves test 08's gate, and editing the Federal Register query moves test
  05's, because both import from `scripts/config.py` rather than keeping a copy.
