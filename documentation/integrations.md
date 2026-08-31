---
title: Integrations
source_files: [scripts/data/, scripts/breadth/, scripts/summarize.py, scripts/tts.py, scripts/notify.py, scripts/config.py, .github/workflows/]
entry_points: [GEMINI_API_KEY, NTFY_SUB, PAGE_URL]
last_verified: 2026-08-11
---

# Integrations

All external services are free tiers. Secrets are passed as environment variables. No credential
values live in the repo. Environment variable names only are listed here.

## Yahoo Finance (chart API)

- Used for: the four headline market numbers (S&P 500, Nasdaq Composite, VIX, 10-year Treasury yield).
- Auth: none. Keyless chart endpoint (unlike most free tiers, it includes indices).
- Invoked in: `scripts/data/market.py` (`_yahoo_series`).
- Endpoint shape: `https://<query1|query2>.finance.yahoo.com/v8/finance/chart/<SYMBOL>?range=5d&interval=1d`.
- Symbols: `^GSPC`, `^IXIC`, `^VIX`, `^TNX` (see `config.YAHOO_SYMBOLS`); `^TNX` is the 10-yr yield in
  percent. The last two SETTLED daily closes give value + day-over-day change; a bar belonging to the
  still-open session (per the payload's `currentTradingPeriod`) is dropped, and with only one settled
  close in the window `change` is `null`, never a fabricated 0.
- Notes: a browser-like User-Agent is required. The client tries the query1 then query2 host and uses
  a short `config.MARKET_TIMEOUT` so a hung source fails fast instead of risking the job timeout.
  Missing/null closes (holidays/gaps) are skipped; any failure degrades that number to None.
- History: v1 originally used FRED's keyless CSV, which went unreachable from CI (and locally); Stooq's
  keyless CSV is now behind a JS anti-bot challenge — Yahoo's chart API was the working keyless source
  that still includes indices.

## TradingView scanner (breadth)

- Used for: market breadth — % of S&P 500 / Nasdaq-100 members above their 200-day MA.
- Auth: none. UNOFFICIAL endpoint — treated accordingly (single daily call, full try/except,
  per-index MIN_MATCH fail-close, last-good cache in state.json).
- Invoked in: `scripts/breadth/percent_above_ma.py` — one POST to
  `https://scanner.tradingview.com/america/scan` for the top `BREADTH_SCAN_LIMIT` (2000) US
  common stocks' `close` + `SMA200`. The `type=stock` filter is load-bearing: without it,
  ~430 ADR/fund rows displace S&P names and coverage collapses below the gate.
- Deliberately NOT via the `tradingview-screener` library — that would add pandas+lxml to the
  push-capable CI job for a one-endpoint JSON call.
- Validated vs published indexes ($S5TH, $NDTH) within <1 point.

## Wikipedia (index constituents)

- Used for: the current S&P 500 (~503) and Nasdaq-100 (~101) member lists that breadth
  intersects against.
- Auth: none; needs the project User-Agent (default UA is blocked).
- Invoked in: `scripts/data/constituents.py`, stdlib regex over each page's `constituents`
  table. NOTE the row shapes differ: S&P tickers are LINKED first cells, Nasdaq-100 tickers are
  PLAIN-TEXT first cells. Fail-closed on implausible counts (450–520 / 90–110).

## Wikipedia action API (Alphabet Soup source material)

- Used for: the ONE article each Owen's Alphabet Soup lesson is written from. This is the section's
  accuracy mechanism, not a convenience — the article is fetched before any lesson prose exists, and
  a lesson that cannot be grounded is simply not written that day.
- Auth: none. `https://en.wikipedia.org/w/api.php`, `action=query&prop=extracts|pageprops|info`,
  `explaintext=1&redirects=1&formatversion=2`. Needs a contact-bearing User-Agent
  (`lessons.WIKI_UA`, module-local like the PMMS and Utah UAs).
- Invoked in: `scripts/data/lessons.py` (`fetch_article`, `first_usable`), through `data/retry.py`.
- Why `formatversion=2`: it returns `pages` as a LIST. The legacy shape is a dict keyed by page id
  with `"-1"` for a miss — exactly the shape a caller mis-reads as a hit.
- Fail-closed on four shapes, each logged with its own reason: `missing`, `invalid`,
  `pageprops.disambiguation`, and an extract under `LESSON_MIN_SOURCE_CHARS`. The disambiguation
  check matters most: those pages are real and long and about nothing, so a lesson built on one
  would pass every later guard.
- Verified 2026-08-11 by `10-lesson-sources.py`: all 50 seed titles resolve (4,001–81,805 chars),
  a nonexistent title and `Mercury` (a disambiguation page) both return None.
- Redirects resolve server-side, so the citation points at the article that was actually read.

## Federal Register API

- Used for: the federal half of "Policy that affects you" — rules and proposed rules from the six
  agencies whose output can create a number, a deadline or an obligation for this reader.
- Auth: none, no key, no registration. JSON.
- Invoked in: `scripts/data/policy.py` (`_fr_url` / `_federal_candidates`). ONE request per run
  covers all six agencies: `https://www.federalregister.gov/api/v1/documents.json` with
  `conditions[type][]=RULE&conditions[type][]=PRORULE`, a `publication_date[gte]` window of
  `FR_WINDOW_DAYS` (45), repeated `conditions[agencies][]` params, and an explicit `fields[]` list.
- Agencies (`config.FR_AGENCIES`): HUD, FHFA, CFPB, IRS, **EBSA** and the Education Department.
  Deliberately `employee-benefits-security-administration` and NOT the parent `labor-department`:
  measured 2026-08-03, the parent returned 46 documents in 45 days of which 26 were Labor — almost
  entirely OSHA chemical-exposure limits and Mine Safety rules, none of which can touch this reader.
  Narrowing to EBSA (health plans + retirement) cut the set 46 → 21 with zero loss of relevant items.
  Filtering noise at the source beats spending model tokens rejecting it.
- Notes: uses the project `config.USER_AGENT` (no browser UA needed). Measured volume is 21
  documents per 45 days, so `per_page=100` covers the window ~5× over. Every result URL is on
  `www.federalregister.gov`, which is what makes the host allowlist in
  `summarize._validate_policy_items` enforceable in code rather than asserted in a prompt.
- Failure modes worth knowing: a MISSPELLED agency slug returns HTTP 400, not an empty set, so a typo
  fails loudly instead of silently deleting that agency's coverage. Volume past `per_page` is dropped
  SILENTLY by the API — production logs a `WARNING ... per_page=N truncated the window` line whenever
  `count` exceeds the returned rows. A zero-result response is treated as a broken query and raises.
- Why one API rather than per-agency feeds: CFPB, FHFA, IRS and HUD rulemaking all lands here anyway,
  and each of their own feeds is dead or key-gated (see "Probed and deliberately not used" below).

## Utah Legislature (passed-bills scrape)

- Used for: the Utah half of the policy section — bills the governor actually signed, i.e. that
  became law. Higher signal than the federal half, and dark for ~9 months a year.
- Auth: none, and no published API: Utah documents no bulk feed, and its "Bill Data" link is an
  iframe wrapper rather than a dataset. So the list of signed bills is HTML-scraped, while each
  bill's TEXT comes from the undocumented per-bill JSON the bill page itself renders from (below) —
  undocumented means unversioned, which is why the fallback and A5 exist.
- Invoked in: `scripts/data/policy.py`. The list page is
  `https://le.utah.gov/asp/passedbills/passedbills.asp?session={session}` (e.g. `2026GS`); bill
  text is fetched lazily, one bill per released queue item (from the bill JSON, not the bill page —
  see below).
- **Needs a browser-like User-Agent.** `le.utah.gov` is fronted by a filter unfriendly to
  non-browser agents; the project UA is unprobed there. The string lives module-local as
  `policy.POLICY_UA`, following `market.YAHOO_UA` — a per-host quirk belongs beside the code with the
  quirk, not in `config.py` where it would read as the project's identity.
- Parsing: stdlib regex only. No HTML-parsing dependency is permitted in the push-capable CI job
  (the same constraint `constituents.py` works under). A row is an anchor whose text is the bill
  number followed by nbsp-separated title / sponsor / dates / status; only rows carrying `GSIGN`
  were signed. Measured 2026-08-04: 495 rows, 495 parseable titles, 491 signed.
- **The effective date comes from this table and nowhere else.** The passed-bills table has an
  "Effective Date" column and it is complete: 495/495 rows of 2026GS, 550/550 of 2025GS and 547/547
  of 2024GS, every one `MM/DD/YYYY` (measured live 2026-08-04). The per-bill JSON below has NO
  effective-date field — its only date is `lastActionDate`, the governor's action date (probed
  across HB0068 / SB0060 / SB0236), so nothing else publishes it. The column's position is read
  from the table's own HEADER row rather than hardcoded, because the cells are positional: a column
  inserted upstream would otherwise shift the *passed* date into the effective date, and a wrong
  effective date renders exactly like a right one. Deriving the index from the header turns that
  same change into "no date" — a visible absence instead of a plausible lie. Nothing derives a date
  from the passage date or from Utah's statutory 60-days-after-sine-die default; where that default
  applies, the table already prints the resolved date (368 of 491 signed 2026GS bills read
  05/06/2026). Because the harvest runs once a year while the queue drains over months, the date is
  carried on the queued stub, carried back by `requeue_utah()`, and backfilled onto stubs queued
  before the field existed by `_backfill_utah_dates()` (one list request, once). Gate 07's **A6** is
  the fail-closed guard: it goes red if the column is renamed or removed, which would otherwise be
  silent — a dateless bill simply never reaches "What's coming".
- **Row hrefs are RELATIVE** (`/~2026/bills/static/HB0001.html`) and are `urljoin`ed against
  `UTAH_BASE_URL`. Left un-joined they would fail the host allowlist and drop 100% of Utah items
  while every other gate stayed green — a fully silent dead leg. `07-utah-bill-detail.py` exists
  specifically to keep that proven.
- Bounds: a bill page (the fallback path below) is ~38 KB and strips to ~4,700 characters in ~0.06s;
  abstracts are cut to 2,000 characters, because an unbounded source text would make the
  invented-figure guard vacuous. The annual harvest fetches NO bill text at all — 491 sequential
  requests would threaten the 10-minute job budget — so the queue drains at most `MAX_POLICY_ITEMS`
  (3) detail fetches per run.
- **The bill text lives in the bill JSON, not the bill page.** `/~2026/bills/static/HB0068.html` is a
  JavaScript shell: `/js/rexBill.js` calls `loadBillJSON()` and paints `#docheader` / `#billbox` from
  `https://le.utah.gov/data/{session}/{number}.json`, so the served HTML carries those containers
  EMPTY and its first ~1,800 stripped characters are the site's global navigation.
  `policy._fetch_bill_detail` therefore reads the same JSON the page reads and keeps the
  legislature's own plain-language summary — `generalProvisions` + `highlightedProvisions` +
  `moniesAppropriated` — measured at 123–4,233 characters across 52 signed bills from 2025GS and
  2026GS, every one of which reads like a bill ("This bill: enacts... amends... repeals..."). It
  keeps the provisions ONLY: the bill number and title are already separate candidate fields, and
  prepending them would make "the text names this bill" true even on a run where this leg returned
  nothing.
- Fallback, and the failure mode that remains: when the JSON is unreachable, its session/number
  cannot be derived from the id or URL, or it carries under 80 characters of provisions, the
  extractor falls back to the HTML page sliced to `<main>` (then to everything after `</header>`,
  then to the whole document) and PRINTS the bill and the reason. Nothing raises, so a changed JSON
  shape costs TEXT QUALITY rather than the leg — which is exactly why the guard is an executable
  test rather than an exception. `07-utah-bill-detail.py`'s A5 asserts on the precise
  `summarize.POLICY_PROMPT_TEXT_CHARS` (500) slice the model receives, built through production's own
  `_normalize_utah` + `_policy_docs_block`: it must read like a bill (fail-closed) and contain no
  navigation marker (fail-loud), with `UTAH_CHROME_CONTROL=true` — which replays the pre-fix
  whole-page strip — as the proven negative control. That check exists because the whole-page strip
  shipped once: the model received half a kilobyte of chrome and no bill text, and the
  invented-figure guard compares against that same string, so every Utah item carrying a number was
  dropped too. Silent by construction — the section just stayed quiet. The fingerprint's `model_sees`
  field now shows a human exactly what is being fed.

## Freddie Mac PMMS (mortgage rate)

- Used for: the 30-year fixed mortgage rate, rendered as a fifth market tile. The only part of the
  policy feature with content 52 weeks a year.
- Auth: none. Plain CSV: `https://www.freddiemac.com/pmms/docs/PMMS_history.csv` (~2,889 rows,
  ~150 KB, oldest-first, `M/D/YYYY` dates — so the LAST row is the current release).
- Invoked in: `scripts/data/mortgage.py` (`get_rate`). The rate is read by COLUMN NAME (`pmms30`),
  never by position, so an inserted column shifts nothing.
- Returns `{value, change, asof}`. `change` is the week-over-week move in percentage points, taken
  from the row BEFORE the last — the whole history is already in memory, so it costs no second
  request — and it is `None` (never `0.0`) when there is no usable prior row. It is framed as "vs
  the previous RELEASE" rather than "vs 7 days ago": if Freddie Mac ever skips a week the delta is
  still exactly "the move since the last published rate" instead of a broken weekly claim. The tile
  renders it in bps ("+8 bps"), matching the 10-year Treasury tile.
- **Needs a browser-like User-Agent** (`mortgage.PMMS_UA`, module-local for the same reason as the
  Utah one).
- Notes: the survey is released WEEKLY (Thursday), so on most mornings the newest row is several days
  old — that is this source's healthy state, not staleness, and there is deliberately no freshness
  guard in production because one would false-alarm every Monday. A genuinely stalled feed, a moved
  column or a changed date format is caught by the weekly assumption gate instead
  (`05-policy-sources.py` P4 bounds the row age at 14 days). Any failure returns None with a logged
  reason; a response that hits the read cap is discarded rather than parsed, because a truncated row
  still parses — as a wrong rate.

## Probed and deliberately not used

Every source below was probed on 2026-08-03 and rejected. It is recorded here so nobody re-explores
the same dead ends; do not re-add any of them without re-probing first.

| Source | Result |
| --- | --- |
| Congress.gov API | HTTP 403 without an api.data.gov key — key-gated, not keyless |
| CFPB newsroom feed | HTTP 403 to both bot and browser user-agents |
| FHFA / IRS / HUD RSS | HTTP 404 at every documented-looking path |
| Utah Tax Commission RSS | HTTP 200 but ZERO entries — a published-but-dead feed |
| propertytax.utah.gov | HTTP 200 but JS-rendered; a static fetch yields no Truth-in-Taxation text |
| Utah Housing Corp feed | HTTP 403 / 503 |
| `le.utah.gov` bulk "Bill Data" | an iframe wrapper, not a downloadable dataset |

CFPB, FHFA, IRS and HUD rulemaking is covered by the Federal Register query anyway — which is
precisely why that one API is the backbone instead of a collection of per-agency feeds.

### Adding `conditions[type][]=NOTICE` — measured and rejected 2026-08-03

A standing suggestion is that the annual dollar figures this section most wants — the conforming
loan limit, IRS bracket and standard-deduction adjustments, 401(k)/HSA/IRA contribution limits —
are published as Notices rather than Rules, and are therefore one query parameter away. **They are
not.** Measured against the live API:

| Query, our six agencies, 45 days | Documents |
| --- | --- |
| `RULE` + `PRORULE` (shipped) | 21 |
| adding `NOTICE` | 114 — **5.4x the candidate volume** |

And the figures still would not appear, because they are not in the Federal Register **at any
document type**. Full-text search across ALL types over 400 days:

- `"conforming loan limit"` — 1 hit, and it is a Rule about Enterprise Housing Goals, not the
  annual limit announcement
- `"inflation adjusted items"` (the phrase IRS revenue procedures use for brackets) — **0 hits**
- `"cost-of-living adjustments limitations"` (the phrase for retirement contribution limits) — **0**

FHFA announces the conforming loan limit by press release; the IRS publishes brackets and
contribution limits in the Internal Revenue Bulletin. Neither is a Federal Register document, and
neither has a machine-readable feed (the FHFA/IRS RSS row above). So the trade is 5.4x the noise
for none of the target content.

What this leaves: the section covers **rulemaking effects**, not annual number announcements. The
brief's original static policy calendar was the right mechanism for the latter precisely because
those announcements have no feed to watch — it was cut for having no staleness story, and the gap
it covered is real. Re-adding a small dated calendar is the honest fix, not widening this query.

### The static policy calendar — the answer to the paragraph above (shipped 2026-08-03)

`config.POLICY_CALENDAR` closes that loop. It is **not an integration**: nothing is fetched, there is
no host, no timeout, no key, no failure mode, and it is recorded here only because it is the
deliberate substitute for the feeds this file lists as dead. Eight recurring annual events —
FHFA's conforming loan limit, the IRS bracket/standard-deduction and retirement-limit adjustments,
ACA open enrollment opening and closing, the federal filing deadline, the Utah general session, Utah
Truth in Taxation hearings — resolved forward by `policy.upcoming_calendar()` and emitted as
`briefing.json`'s `policy_calendar`.

Hardcoding is normally the wrong answer and it is the right one here for one reason: **there is
nothing to poll.** Every row in the table above and every measurement in this section says so.

The three properties that keep a hardcoded list from rotting, each enforced by
`09-policy-calendar.py` rather than asserted here:

1. **No entry carries a year.** Each is a month/day rule resolved against the run date, so an entry
   rolls into next year the day after it passes and cannot become a past date on a page that says
   "What's coming". C1 checks this from 40 reference dates including December 31 and January 1; the
   `no-rollforward` control replaces the resolver with the naive same-year version to prove C1 is
   really measuring it.
2. **Every label is anticipatory** — "expected late November", never "November 25". This is the same
   rule as the model never authoring a figure, applied to dates: we do not state a date the source
   has not announced. C5 enforces it mechanically (the label must contain "expected" and must carry
   no year and no "Month DD"). The client reinforces it: a calendar row renders a muted **Expected**
   where a reported item renders its real effective date, and the resolved ISO date is used only to
   order the list, never printed.
3. **The month/day is the END of the plausible window**, not a guess at the date — so an entry stays
   visible for the whole period the event could land in and never rolls forward while the event is
   still ahead.

Each URL was fetched on 2026-08-03 and returned HTTP 200 (`fhfa.gov/data/conforming-loan-limit`,
two `irs.gov` pages, `healthcare.gov/quick-guide/dates-and-deadlines`, `irs.gov/filing/individuals/
when-to-file`, `le.utah.gov/session`, `propertytax.utah.gov`). They exist for a human to tap; nothing
fetches them at runtime. Note that `le.utah.gov`'s code and bill pages are JavaScript shells (the
same quirk documented under "Utah Legislature" above), so the Utah entries' TIMING is sourced from
the published statutory rule and the observed record, not from a machine-readable page.

The calendar deliberately does **not** touch `data_availability`: it cannot be unavailable, and
folding it in would let a healthy calendar mask a dead Federal Register leg.

## Google Gemini

- Used for: writing the briefing prose (tldr, the why lines, tech and world items, weekly recap),
  writing the policy section's two prose fields, choosing and writing the day's Alphabet Soup
  lesson, and synthesizing the audio (`scripts/tts.py`, model `TTS_MODEL` =
  `gemini-2.5-flash-preview-tts`, voice `TTS_VOICE` = Kore; mp3 encoded in-process with `lameenc`).
- Request budget per build: **4 text calls** (narrative, policy, lesson topic, lesson prose — the
  last two skipped when the deck already grew, the policy one skipped on an empty window) and
  **4 TTS calls** (the briefing edition plus three lesson clips), up from 1 TTS call before v4.
  `tts._pace()` keeps at least `LESSON_TTS_MIN_INTERVAL` (20s) between TTS requests because the free
  tier limits per MINUTE as well as per day, and `LESSON_AUDIO_DEADLINE` (420s into the run)
  abandons any remaining lesson clips rather than risk the job's 10-minute cap.
- Auth: env var `GEMINI_API_KEY`. Free tier. Keep the Google project's billing disabled to stay free.
- Invoked in: `scripts/summarize.py` via the `google-genai` SDK (`genai.Client`).
- Model: `config.MODEL_ID` (`gemini-2.5-flash`) with `config.MODEL_FALLBACK` (`gemini-2.5-flash-lite`).
  Structured output uses `response_mime_type="application/json"` plus a `response_schema`.
- Privacy: on the free tier Google may use submitted content and output to improve products, and
  human reviewers may see it. Only public news is sent. No personal data. No secrets.
- Resilience: the call tries the primary model then the fallback. If both fail the pipeline writes a
  no-AI briefing (raw numbers plus headlines).
- Second call (policy): `summarize_policy()` is a separate, CONDITIONAL request — it is skipped
  entirely on any day with no un-seen candidates, which is most days. It runs `config.MODEL_ID` only,
  with NO fallback loop and a 60s client timeout, where the narrative call loops two models at 120s
  each. The asymmetry is deliberate: losing the narrative loses the briefing, but a failed policy
  call degrades one section and retries tomorrow, whereas overrunning `briefing.yml`'s
  `timeout-minutes: 10` cancels the job and ships nothing at all.
- Third and fourth calls (Alphabet Soup): `propose_lesson_titles()` returns exact article titles and
  NO prose — splitting subject choice from writing is what lets a real article be fetched in between,
  and it is why the model can never write a lesson from memory. `summarize_lesson()` then writes from
  that article and loops primary→fallback on a *validation* rejection as well as on an error, since
  an invented figure is per-generation rather than per-prompt. Both return empty/None instead of
  raising: a failed lesson leg means the deck does not grow that day, and the reader still has every
  lesson they have not finished.
- Every prompt fences untrusted third-party text and declares it non-instructional
  (`ARTICLES_BEGIN`/`ARTICLES_END` for news, `DOCS_BEGIN`/`DOCS_END` for policy documents,
  `ARTICLE_BEGIN`/`ARTICLE_END` for the lesson's source article).
- `data-smoke.yml` also spends one Gemini call per weekly run, in `06-policy-relevance.py`, using the
  same `GEMINI_API_KEY` secret. The two lesson gates (`10`, `11`) spend none — they exercise the
  fetch boundary and the shipped guards, not the model.

## ntfy

- Used for: the morning "ready" push (sent by the workflow ONLY after `git push` succeeds — see
  `python -m scripts.notify ready`), two-tier market-breadth alerts per index (one-shot warning
  below 40%, daily high-priority oversold nag below 30%), a policy push, self-monitoring health
  pings, and the `data-smoke.yml` / `shell-guard.yml` failure alarms (both sent by curl from the
  workflow, not by `notify.py`).
- Policy pushes (`notify.policy_alert`) fire once per newly-reported FINAL rule, at NORMAL priority
  on purpose: a rule taking effect weeks from now is a heads-up, not the wake-you-up page that
  breadth OVERSOLD is. Proposed rules never push (nothing has taken effect) and queue-released Utah
  bills never push (an annual backfill is not news). One-shot per date via `policy_today.alerted`,
  so a `--force` rebuild cannot re-push.
- Auth: none. The topic name is the access control, so it must be long and unguessable.
- Config: the code reads env var `NTFY_TOPIC`; the GitHub secret is named `NTFY_SUB` and the
  workflows map `secrets.NTFY_SUB -> NTFY_TOPIC`. Invoked in `scripts/notify.py` (POST to
  `https://ntfy.sh/<topic>`). If `NTFY_TOPIC` is unset every push is silently skipped.
- Headers used: Title, Priority, Click (the tap-through URL). The morning push taps through to
  `PAGES_URL`.
- Privacy note: anyone who knows the topic can read and publish to it. This is acceptable for a
  single user with no personal data, but the topic must not be shared.

## RSS news feeds

- Used for: world, business, and tech candidate articles fed to the summarizer.
- Auth: none. Parsed with `feedparser` in `scripts/data/news.py`.
- Feed lists: `config.WORLD_FEEDS`, `config.BUSINESS_FEEDS`, `config.TECH_FEEDS`.
- Current feeds: BBC World, Al Jazeera, Guardian World, NPR (world); MarketWatch, Yahoo Finance,
  CNBC (business); Ars Technica, The Verge, MIT Technology Review, Hacker News (tech).
- Notes: each feed is fetched in a try/except so one outage cannot abort the run. Items older than
  `config.NEWS_WINDOW_HOURS` are dropped. Titles and URLs are de-duped. Each bucket is capped.

## GitHub Pages and GitHub Actions

- Used for: hosting the PWA (Pages) and running the daily job (Actions).
- Auth: the built-in `GITHUB_TOKEN` pushes the daily commit. No personal access token.
- Config: the code reads env var `PAGES_URL` (the public site URL, used in the notification Click
  header and by the heartbeat); the GitHub repo variable is named `PAGE_URL` and the workflows map
  `vars.PAGE_URL -> PAGES_URL`. If unset it falls back to a placeholder URL.
- Notes: the repo must be public for free Pages and unlimited Actions minutes. Pages serves from
  branch `main`, folder `/docs`.

## Twelve Data (unused)

- Used for: nothing. It was staged for v2 breadth, but v2 shipped keyless via the TradingView
  scanner instead. `scripts/data/twelvedata.py` is kept only as a possible future source; no
  workflow maps its key.

## Environment variables and GitHub config (names only)

The code reads env vars; the workflows source those from GitHub secrets/variables, whose names differ
for ntfy, Pages, and Twelve Data. Configure the GitHub name; the workflow maps it to the env var.

| GitHub secret/variable | Env var the code reads | Scope |
| --- | --- | --- |
| Secret `GEMINI_API_KEY` | `GEMINI_API_KEY` | v1, required |
| Secret `NTFY_SUB` | `NTFY_TOPIC` | v1, required for notifications |
| Variable `PAGE_URL` | `PAGES_URL` | v1, tap-through link + heartbeat target |
| Secret `TWELVE_API_KEY` | `TWELVEDATA_API_KEY` | unused (client staged only) |
| (none) | `MODEL_ID` | optional Gemini text-model override |
| (none) | `TTS_MODEL` / `TTS_VOICE` | optional audio-edition overrides |
| (none) | `BRIEFING_STATE_PATH` | optional state-file override — LOCAL DEV ONLY, see `operations.md` |

The Federal Register, Utah Legislature and Freddie Mac PMMS sources need no key, no registration and
no GitHub configuration at all. Nothing has to be added to either workflow for the policy section:
`briefing.yml` already carries `GEMINI_API_KEY`, and `data-smoke.yml` reuses the same secret.

A name mismatch is no longer fully silent: both workflows FAIL FAST at startup when
`secrets.NTFY_SUB` is empty (a missing topic would disable every alarm path), and `config.py`
falls back to the placeholder even when `PAGES_URL` arrives as an empty string (unset repo
variable). The mapping lives in `briefing.yml` and `heartbeat.yml`.

## Supply-chain posture

The daily job holds a write token plus the Gemini/ntfy secrets, so its inputs are pinned:
`requirements.txt` is exact-pinned, transitives are locked by a CI-frozen `constraints.txt`
(refresh: copy the "Successfully installed" line from a green run after changing requirements),
and all actions are pinned by commit SHA. `shell-guard.yml`, `guard-triggers.yml` and
`data-smoke.yml` are the
fail-closed/diagnostic guards.
