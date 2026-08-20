# Briefing — Assumption Tests

Pre-flight + regression tests that prove the **load-bearing runtime assumptions** of the
personal morning-briefing project against the real external services it depends on. Text review
can't validate "does a 600-symbol pull work from a GitHub Actions runner" or "does Gemini return
valid structured JSON" — these tests do, by running against the real thing.

These are **assumption tests** (narrow-and-deep, run against real infra), not unit tests
(pure logic vs mocks) and not smoke tests (broad-and-shallow). Two deliberate exceptions are pure
logic with no external service at all, and both live here for the same reason: what they guard is a
runtime assumption nothing else in the system can detect going wrong. `09-policy-calendar.py` guards
the hardcoded `POLICY_CALENDAR`; `12-narration-mirror.py` guards the two hand-mirrored narrations against drift; `11-client-pointer.js` guards the lesson pointer, which lives in the
browser's localStorage and is therefore invisible to every server-side check in this repo.

## Safety

Every test refuses to run unless `BRIEFING_SMOKE_ALLOW_DEV=true` is set. Every test is read-only
against external services: `03-gemini-structured.py` sends one prompt to Gemini and
`06-policy-relevance.py` sends three, but neither publishes or writes anything anywhere outside this
directory's fingerprint files. 06's G8 additionally calls `policy.get_policy()` twice — read-only,
one Federal Register request each, on a synthetic state whose Utah queue is empty and whose session
is already stamped, so neither the annual 491-row harvest nor any detail fetch runs, and the
returned state is discarded.

## What each test proves

| Test | Proves | Needs |
|---|---|---|
| `04-external-boundary-smoke.py` | RSS feeds parse + enough fresh items in 72h + ≥1 world feed alive; Wikipedia S&P500/NDX tables parse to ~500/~100 via header-matched column; symbol normalization output is stable | nothing (runnable now); `feedparser`, `pandas`, `lxml` |
| `05-policy-sources.py` | the Federal Register API answers one multi-agency, type-filtered, date-windowed query with all fields the item format needs; every result URL is on federalregister.gov so the `.gov` guard is code-enforceable; volume stays bounded; Freddie Mac PMMS CSV parses and is fresh; the Utah Legislature passed-bills page is scrapable to (number, title, signed-status) — Utah publishes no JSON API. The FR query shape (`FR_API`/`FR_AGENCIES`/`FR_FIELDS`/`FR_WINDOW_DAYS`/`FR_PER_PAGE`) is IMPORTED from `scripts/config.py`, so the gate follows what production actually sends | nothing (runnable now) |
| `07-utah-bill-detail.py` | 3 rows sampled from the LIVE passed-bills page (≥1 HB, ≥1 SB) resolve via `urljoin` to absolute `https://le.utah.gov/` URLs (A1); each bill's detail page returns 200 under the exact UA production sends (A2); **production's own** `policy._fetch_bill_detail` yields ≥ the floor (A3 — now 100, not 200: the shortest real bill summary measured across 52 signed bills was 123 chars, so 200 would have gone red on a short-but-good bill); body size and per-fetch wall time sit under stated ceilings (A4); and **A5 — the assertion this file now exists for: the exact `summarize.POLICY_PROMPT_TEXT_CHARS` slice that REACHES THE MODEL must read like a bill (fail-closed) and must contain no navigation marker (fail-loud).** The earlier version of this test passed while the model was receiving ~500 characters of site navigation, because it asserted against the full 4,700-character stripped page instead of the slice that actually ships — that is why A5 exists. Title tokens are recorded in the fingerprint but deliberately NOT asserted (3 of 20 measured bills paraphrase their own title, so a hard check there would be a flaky gate). **A6 asserts the passed-bills "Effective Date" column is still readable** on ≥ 95% of signed rows, across EVERY signed row rather than the 3-row sample — that table is the ONLY published source for a Utah bill's effective date (the per-bill JSON has none), and a bill without one can never enter `policy_active` or "What's coming", so the column going dark is silent by construction. Measured 495/495, 550/550 and 547/547 across 2026GS/2025GS/2024GS; negative control `UTAH_EFF_DATE_MIN_SHARE_OVERRIDE=1.01` forces it red. The test imports production (`policy.POLICY_UA`, `_fetch_bill_detail`, `_normalize_utah`, `_parse_rows`, `_effective_date_index`, `summarize._policy_docs_block`) rather than holding local copies | nothing (runnable now) |
| `08-prefilter-recall.py` | the LIFE_PROFILE keyword prefilter — which sits UPSTREAM of the only component 06 proves — retains both documents the live model selected (pinned by `document_number` so the fixture cannot age out) and 4 known-relevant Utah bills on title alone; admits **none** of 4 decoys; admits ≤18% of the ~491 live signed Utah bills (an over-broad prefilter turns `MAX_POLICY_ITEMS` truncation into a lottery); and the word-boundary matcher handles `rent`/*current*, `mortgage`/"mortgages", and `401(k)`. Imports `config.LIFE_PROFILE_KEYWORDS`, so broadening the shipped list moves this gate with it | nothing (runnable now) |
| `09-policy-calendar.py` | C1–C6: the one HARDCODED leg of the policy section cannot rot. Every `config.POLICY_CALENDAR` entry resolves FORWARD from 40 reference dates including Dec 31 and Jan 1 (a November entry seen in December must resolve to next November, never to a past date under a "What's coming" heading) and lands within 366 days; no entry carries a year as a key or inside its label; every entry has a valid month/day, a non-empty label, a non-empty note and an `https` URL; the horizon filter returns entries in ascending date order; **every label reads as anticipatory** — it must contain "expected" and must contain no 4-digit year and no precise "Month DD", which is the model-never-authors-a-figure rule applied to dates; and the shipped horizon leaves the block empty on a meaningful share of mornings (measured over a full year: 159/365 = 43.6%), because a horizon wide enough to show something every day would silently turn a render-when-non-empty section into an always-on one. Imports `config.POLICY_CALENDAR` and `policy._next_occurrence`/`upcoming_calendar`, so editing the shipped calendar moves this gate with it. **The only gate that needs neither a key nor a network** — it is pure logic, runs in milliseconds, and exists because a rotted calendar entry renders exactly like a good one | nothing (offline) |
| `10-lesson-sources.py` | L1–L6: Owen's Alphabet Soup can only teach what a real article says. Every title in `config.LESSON_SEED_ARTICLES` fetches, is not a disambiguation page and clears `LESSON_MIN_SOURCE_CHARS` (the seeds are the FLOOR under the section — when the model's proposals do not resolve, the day's lesson comes from that list, so a rotted title is a silently missing lesson); a nonexistent title and a known disambiguation page both return None, which is what stops a near-miss article from becoming a "grounded" lesson about the wrong subject; **production's `summarize._validate_lesson` rejects a dollar amount, a percentage or a year that is absent from the article and accepts the identical prose without it**; anything shaped like a drug dosage is rejected whatever the article says; a segment outside the shipped word bounds is rejected; and **L6 asserts the tier list agrees across `tts.compose_lesson_segments`, `config.LESSON_WORD_TARGETS` and docs/app.js's `SOUP_TIERS`** — three copies of one list in two languages, where drift means the phone asks for a clip the build never names. Imports production throughout | nothing (L1/L2 need network; L3–L6 offline) |
| `11-client-pointer.js` | C1–C8: **the lesson pointer advances ONLY when the briefing actually finished.** This is the one rule in the project enforced entirely in the browser — the build cannot know whether the audio reached the end, so `docs/app.js`'s `soup` object IS the feature and no server-side check could ever see it regress. Runs the SHIPPED app.js against a minimal DOM in Node: the section renders last showing the oldest unfinished lesson; the queue chains today's mp3 → the chosen tiers' clips → the shared outro; the length setting changes both the page and the queue and persists; reaching the end of the queue records a COMPLETION and advances; the "New lesson" button advances but records a SKIP (the two must stay distinguishable or "did he listen" stops meaning anything); a lesson whose clips are missing falls back to the device voice rather than to silence; a finished deck says so instead of the narration handing off into nothing; and the history survives a reload | nothing (offline, no key; Node only) |
| `12-narration-mirror.py` | C1–C2: **the mp3 script and the device-voice script cannot drift apart.** The briefing is spoken by two hand-mirrored implementations — `scripts/tts.py compose_script()` for the daily mp3 and `docs/app.js speechText()` for the phone's own voice on a fallback day — and nothing in production ever compares them, so a change made on one side only turns a fallback day into a quietly different briefing. Runs both against six fixtures (Monday vs non-Monday, present vs absent mortgage, null `change` on every number, a Sunday recap, a story cross-filed in tech and world, a fully degraded briefing) and requires BYTE equality, then asserts each fixture really exercised its branch so equality cannot pass by comparing two empty strings. Pins the cross-language trap that Python's `date.weekday()` is Monday=0 while JavaScript's `Date.getDay()` is Sunday=0 | nothing (offline, no key; Python + Node) |
| `06-policy-relevance.py` | G1–G8: the model, given the production `LIFE_PROFILE` and a real candidate set, selects only documents that create a number/deadline/obligation; every citation joins back through the production `_norm_url` to a fetched document on one of the two primary `.gov` hosts; every item has a non-empty `effect`; it **rejects three seeded real-but-irrelevant decoys** (OSHA benzene, mine ventilation, blacksmith shops) so a model that just returns the first N cannot pass; invents no dollar amount or percentage absent from the source; writes no hedge word in a settled-law `effect`; two live tilde-bearing Utah bills round-trip; and **G8 asserts THE BATCH INVARIANT — production must never hand the model fewer documents than a batch.** G8 used to be two one-document probes closing the "1-of-1 vs best-2-of-24" seam, and it went RED on CI run 30851392524 (given ONE on-profile document in isolation the model returned nothing, while ranking a batch of 26 in the same run it selected correctly). The fix removed that mode from production — `policy.get_policy()` now sends the whole prefiltered window and the `policy_seen` dedupe runs after selection — so G8 now calls the SHIPPED `get_policy()` twice, the second time with every returned id marked seen, and goes red if the candidate set shrinks. The two one-document calls still run as a **recorded measurement** (`single_candidate_probe.single_candidate_selects`, printed as a NOTE, asserting nothing): the model limitation is real and worth tracking, and **the model did not get better**. Everything production-shaped is IMPORTED (`policy._federal_candidates`, `summarize.POLICY_SYSTEM`, `PolicySection`, `_MONEY`, `_norm_url`, `_policy_docs_block`) — a rename goes red at import instead of quietly proving nothing. The one deliberate exception is the host allowlist, asserted against a local tuple so widening `_ALLOWED_HOSTS` cannot silently widen this gate | `GEMINI_API_KEY`; `google-genai`, `pydantic` |
| `01-twelvedata-runner-pull.py` | ~600-constituent + index (SPX/NDX/VIX/10Y) daily pull succeeds **from a runner IP** within ~650 credits; class-share symbols resolve | `TWELVEDATA_API_KEY`; **run in CI** for the runner-IP proof |
| `02-twelvedata-seed-budget.py` | a 250-day seed doesn't multiply credits; full ~600 seed fits in one 800/day window; whether seed + same-day daily pull needs to wait for the 00:00 UTC reset | `TWELVEDATA_API_KEY` |
| `03-gemini-structured.py` | which `google-genai` config shape works on the pinned SDK; `resp.parsed` returns a valid schema object (not None) | `GEMINI_API_KEY`; `google-genai`, `pydantic` |

The biggest risk (test 1, runner-IP) is only truly closed when test 1 runs **inside a GitHub
Actions `workflow_dispatch` job** — a local pass proves the API contract but not the runner-IP case
(that is exactly what killed yfinance). That caveat still stands for tests 1 and 2, which are
key-gated and are NOT in any workflow.

It no longer applies to the policy tests. `.github/workflows/data-smoke.yml` runs **05, 07, 08, 09,
10, 11 and 06 from a GitHub runner on a weekly schedule** (`0 16 * * 1`) as well as on dispatch, each as its own
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
| `POLICY_CALENDAR_CONTROL=no-rollforward` | 09 | forces **C1** red — replaces production `policy._next_occurrence` with the naive same-year version (`date(today.year, m, d)`), i.e. exactly the December→January bug the roll-forward exists to prevent. **Exercised 2026-08-03**: exit 1, entries resolving to 2026-11-30 / 2026-01-15 from December and August reference dates |
| `POLICY_CALENDAR_CONTROL=fixed-year` | 09 | forces **C2** red — appends an entry carrying a `year` key and a year inside its label, the shape that makes a calendar go stale. **Exercised 2026-08-03**: exit 1, both C2 assertions fired |
| `POLICY_CALENDAR_CONTROL=blank-note` | 09 | forces **C3** red — appends an entry with an empty note. **Exercised 2026-08-03**: exit 1 |
| `POLICY_CALENDAR_CONTROL=no-sort` | 09 | forces **C4** red — neutralises production's `policy._calendar_sort_key` to a constant; Python's sort is stable, so the output falls back to config order, which in the shipped calendar is the reverse of date order in November. **Exercised 2026-08-03**: exit 1 on four windows. Can only engage while config order differs from date order somewhere — the test says so on stderr if it cannot, because a control that cannot fail proves nothing |
| `POLICY_SEEN_CONTROL=true` | 06 | forces **G8** red — re-applies the pre-prompt `policy_seen` dedupe that was removed from `policy.get_policy()`, i.e. simulates exactly the "optimization" G8 exists to catch. **Exercised 2026-08-03** against the real gate file with the model and network stubbed: normal run exit 0, control run exit 1 with `G8 policy.get_policy() DROPPED 10 of 10 candidate(s) once they were in policy_seen` |
| `POLICY_PROBE_DOC_OVERRIDE=<irrelevant document_number>` | 06 | flips the recorded single-candidate MEASUREMENT and prints its premise NOTE. Since 2026-08-03 it forces **nothing** red — that probe no longer asserts (see 06's docstring). The hard pin on that document is 08's R1, which needs no key |
| `MODEL_ID=<weaker model>` | 06 | the honest way to ask whether the gate measures the model or the prompt — **not yet exercised** |
| `LESSON_CONTROL=blind-figures` | 10 | forces **L3** red — neutralises production's `_MONEY`/`_YEAR` patterns so an invented dollar amount, percentage and year all survive validation. **Exercised 2026-08-11**: exit 1, all three assertions fired |
| `LESSON_CONTROL=allow-dosage` | 10 | forces **L4** red — neutralises production's `_DOSAGE` pattern. **Exercised 2026-08-11**: exit 1 |
| `LESSON_CONTROL=no-length-cap` | 10 | forces **L5** red — raises the production ceiling out of reach. The over-length fixture is built from a ceiling captured BEFORE the control engages; built from the live constant it scaled with the control and the run stayed green, which is exactly the vacuous-control trap this table exists to prevent. **Exercised 2026-08-11**: exit 1 after that fix |

The policy-test controls (05, 07, 08) were each verified to actually go red on 2026-08-03; 02's and
04's date from their own authoring. 06's `POLICY_SEEN_CONTROL` was exercised on 2026-08-03 by loading
the real gate file with `_generate` and the HTTP fetches stubbed (no key, no network) and running
`main()` twice — the deterministic half of 06 needs no model. Its remaining controls
(`POLICY_PROBE_DOC_OVERRIDE`, `MODEL_ID`) still need a CI dispatch; record the result here.

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
in requirements.txt — dev-only deps). Tests 5, 7, 8, 9 and 10 need neither a key nor extra deps, and
9 needs no network either. Test 11 is the one JavaScript gate — it runs the shipped `docs/app.js`
under Node with no network, no key and no dependencies:

```bash
BRIEFING_SMOKE_ALLOW_DEV=true node scripts/briefing-assumptions/11-client-pointer.js
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/12-narration-mirror.py
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/13-us-news-editorial.py
```

Tests 5, 6, 8 and 9 import from `scripts/` (`from scripts import config`; 6 imports the production
policy surface, and 9 imports `policy.upcoming_calendar` / `_next_occurrence` so its controls act on
production rather than on a copy). Running them by bare path from a checkout works — each inserts the repo root on
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
  07, 08 and 09 need no manual step: `data-smoke.yml` runs them from a runner every Monday. (09 has
  no runner-IP question at all — it makes no request — but it rides along so a calendar edit merged
  without running it still surfaces within a week.)
- **Post-ship regression:** re-run after each slice; any FAIL = regression. For the policy legs the
  weekly Data Smoke run is that regression net, and it pages on red rather than emailing.
- **After touching any data source or the policy config:** dispatch Data Smoke. Editing
  `LIFE_PROFILE_KEYWORDS` moves test 08's gate, editing the Federal Register query moves test 05's,
  and editing `POLICY_CALENDAR` moves test 09's, because all three import from `scripts/config.py`
  rather than keeping a copy.
- **After editing `POLICY_CALENDAR`, run 09 before anything else.** It needs no key, no network and
  no dependency, so there is no excuse to skip it — and it is the ONLY thing standing between an
  edited calendar and a wrong date shipped under a "What's coming" heading. Nothing at runtime
  compares a calendar entry to reality.
