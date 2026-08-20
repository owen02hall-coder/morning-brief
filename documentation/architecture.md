---
title: Architecture
source_files: [scripts/, docs/, .github/workflows/]
entry_points: ["python -m scripts.build_briefing", "scripts/build_briefing.py:main", "python -m scripts.heartbeat", "python -m scripts.notify ready"]
last_verified: 2026-08-11
---

# Architecture

A free, single-user morning briefing. A scheduled job gathers market numbers, news, the government
policy that changes a number or a deadline for this one reader, and one grounded lesson worth
knowing for its own sake; an AI writes a short cited summary; the result is published as a static
web app and a push notification is sent. Everything runs in the cloud so the user's devices can be
off. Cost is zero on free tiers.

## Components

- Scheduler: a GitHub Actions workflow (`.github/workflows/briefing.yml`) runs daily on cron.
- Pipeline: a Python package (`scripts/`) that fetches data, summarizes, narrates, and writes output.
- Web app: a static PWA (`docs/`) served by GitHub Pages that renders the output, with a Listen
  player that plays the daily audio edition and then the current Alphabet Soup lesson as one queue
  (on-device speech fallback for any part with no audio).
- Notifications: ntfy delivers a post-publish "ready" push, breadth alerts (two tiers), a
  normal-priority push per newly-arrived federal final rule, and self-monitoring health pings.
- Guards: `shell-guard.yml` fails any push that changes the PWA shell without a service-worker
  CACHE bump; `data-smoke.yml` (weekly + dispatch) proves every data leg — market spine, policy
  sources, the Utah scrape, the keyword prefilter, the lesson seed articles and prose guards, the
  client-side lesson pointer, and the model's relevance judgement — from a runner IP, and pushes
  ntfy when one goes red.

## Data flow

```
GitHub Actions (cron, UTC) --> python -m scripts.build_briefing
  date-gate (build once/day: first cron that lands builds; if last_run == today the rest no-op)
  -> state.load()                          state/state.json
  -> market.get_market()                   Yahoo Finance chart API, keyless (S&P 500, Nasdaq Comp, VIX, 10-yr)
  -> mortgage.get_rate()                   Freddie Mac PMMS CSV, 30-year fixed (weekly release; None on failure)
  -> news.get_news()                       RSS feeds (world, business, tech), per-feed isolation
  -> breadth compute (TradingView scan ∩ Wikipedia constituents, S&P 500 + Nasdaq-100;
     per-index MIN_MATCH fail-close + last-good cache)
  -> _get_policy()                         IF state.policy_today.date == today: re-emit verbatim and STOP
                                           (no fetch, no model call, no push) — this branch is first
     -> policy.get_policy()                Federal Register (6 agencies, 45d) + Utah signed-bill queue
                                           -> one normalized shape -> keyword prefilter
                                           -> cap at MAX_POLICY_CANDIDATES (NO policy_seen filter:
                                              the model is always given the whole window to RANK)
     -> summarize.summarize_policy()       SECOND Gemini call, asks for MAX_POLICY_SELECTIONS (6)
                                           ranked items; skipped only when the window is EMPTY
     -> _new_policy_items()                drop ids already in policy_seen, THEN cut to MAX_POLICY_ITEMS
     -> state.record_policy()              the only writer of policy_seen/policy_active/policy_today
                                           (policy_seen records what was REPORTED, not what was sent)
  -> policy.upcoming_calendar()            STATIC recurring dates (config.POLICY_CALENDAR) resolved
                                           forward against today. No fetch, no model, no state, no
                                           availability flag - called from run(), NOT from
                                           _get_policy(), so it can never be marked seen or pushed
  -> _get_lessons()                        OWEN'S ALPHABET SOUP — text only, audio comes later
                                           IF the deck already holds an entry dated today: STOP
                                           (no fetch, no model call, no audio) — a `--force`
                                           dispatch is the normal manual path, and without this each
                                           one would append another lesson and spend 3 more TTS
                                           requests. Reported as HEALTHY, not degraded
     -> summarize.propose_lesson_titles()  THIRD Gemini call: exact article titles, NO prose at all
     -> lessons.first_usable()             en.wikipedia.org action API, keyless. Fails closed on a
                                           missing page, a disambiguation page or a stub, and walks
                                           to the next candidate. NO ARTICLE, NO LESSON.
     -> summarize.summarize_lesson()       FOURTH Gemini call: writes the lesson FROM that article
                                           -> _validate_lesson() checks the prose back against the
                                              article text in code (invented $/%/year, or anything
                                              shaped like a dosage, discards the whole lesson)
     -> state.record_lesson()              the only writer of lessons_taught (the long dedupe memory)
  -> summarize.summarize()                 Gemini structured output (numbers injected as facts)
  -> assemble briefing dict (incl. breadth, mortgage, policy, policy_upcoming, policy_calendar)
  -> write docs/briefing.json
            docs/archive/<date>.json
            docs/archive/index.json
            headline.txt                   (job-local handoff for the post-publish ready push)
  -> tts.generate(has_lesson=...)          deterministic narration -> Gemini TTS -> audio.mp3 (lameenc, in-process)
                                           has_lesson only claims the DECK is non-empty — whether the
                                           reader has an unfinished lesson is a fact on their phone
  -> _publish_lessons()                    tts.ensure_outro() (once, ever) + 3 clips per new lesson
                                           -> docs/lessons/, abandoned past LESSON_AUDIO_DEADLINE
                                           -> prune audio outside the retention window
                                           -> write docs/lessons.json (audio FIRST, deck SECOND: an
                                              entry only ever claims clips already on disk)
  -> breadth alert eval (warning <40 one-shot / oversold <30 daily nag, per index) -> state
  -> policy alert eval (one normal-priority push per NEW federal final rule; one-shot per date) -> state
  -> state.save (last_run + markets_* + breadth + policy state; last_run rewritten daily -> renewing commit)
  -> health pings if degraded/crashed; breadth alerts via ntfy
workflow: Publish audio edition            audio.mp3 -> docs/briefing-audio.mp3 + date manifest (only on success)
workflow: git commit + push (docs/, state/) --> GitHub Pages redeploys
workflow: Send ready push                  python -m scripts.notify ready — ONLY after git push succeeded
PWA (docs/app.js): fetch briefing.json + lessons.json (network-first) -> render; Listen player
  plays a QUEUE (today's mp3 -> the current lesson's clips at the chosen depth -> the shared outro),
  falling back to chunked speechSynthesis for any part with no audio; archive + search; staleness
  banner; the policy section is built by a function that returns null when nothing qualified and is
  appended behind a guard (see the design decisions below); Owen's Alphabet Soup renders LAST and
  owns the deck pointer in localStorage

Heartbeat (independent cron): python -m scripts.heartbeat
  -> fetch LIVE docs/briefing.json from Pages -> ntfy + non-zero exit if older than HEARTBEAT_STALE_HOURS
```

## Modules

- `scripts/config.py`: all tunables. Timezone, model id and fallback, news window, RSS feed lists,
  Yahoo symbols, the life profile + keyword prefilter list, Federal Register / Utah / PMMS endpoints
  and caps, paths, staleness + heartbeat thresholds. No secrets. Two things deliberately do NOT live
  here: the browser User-Agents that PMMS and `le.utah.gov` require (module-local, following
  `market.YAHOO_UA` — a per-host quirk belongs beside the code with the quirk) and any policy state
  (that is `state.py`'s).
- `scripts/build_briefing.py`: orchestrator and CLI. Date-gate, flag handling, assembly, writing,
  archive index, top-level failure handling. `_get_policy()` owns the policy leg's two load-bearing
  orderings (re-emit before fetch; mark seen only after a successful model call) and the first-run
  bootstrap suppression. It is called AFTER the breadth call, because `_get_breadth()` returns a new
  state dict and passing the pre-breadth `st` onward would silently discard `breadth_last_good`.
- `scripts/data/lessons.py`: the source material for Owen's Alphabet Soup — one keyless English
  Wikipedia article, fetched BEFORE any lesson prose exists. Returns None (with a distinct logged
  reason) for a missing page, an invalid title, a disambiguation page, or an extract shorter than
  `LESSON_MIN_SOURCE_CHARS`; `first_usable()` walks a candidate list until one answers and skips
  articles already in `lessons_taught`. That dedupe runs AFTER the fetch on purpose: redirects mean
  two proposed strings can resolve to one article, and only the fetch knows.
- `scripts/heartbeat.py`: independent liveness check. Fetches the live Pages briefing and pings ntfy
  (and exits non-zero) if it is stale or unreachable. Run by `.github/workflows/heartbeat.yml`.
- `scripts/data/market.py`: the four headline numbers from Yahoo's chart API, recent-window fetch, last-two
  observations for value and day change. Each value may be None.
- `scripts/data/news.py`: RSS fetch and parse into world, business, tech candidate lists. Per-feed
  try/except, time-window cutoff, dedupe, per-bucket cap.
- `scripts/data/mortgage.py`: the Freddie Mac PMMS 30-year fixed rate. Reads the history CSV's last
  row and looks the rate up by COLUMN NAME (`pmms30`), so an inserted column shifts nothing. Returns
  `{value, change, asof}` or None; never raises. `change` is the week-over-week move in PERCENTAGE
  POINTS, computed from the row before the last — the whole file is already parsed in memory, so the
  prior release costs no extra request. It is **None, never 0.0**, when there is no usable prior row
  (the same rule `market.py` follows for a lone settled close: a fabricated zero renders as
  "unchanged", which is a claim about the market, where the truth is "we don't know"). The tile
  renders it in **bps**, the same `numberCard` mode as the 10-year Treasury: the figure already reads
  "6.66%", so a "+0.08%" delta beside it is ambiguous (0.08 percentage points, or 0.08% of the
  rate?), while "+8 bps" cannot be misread and is how rate moves are quoted. There is deliberately no freshness guard: PMMS is a WEEKLY
  Thursday release, so a several-day-old row is its healthy state and an age check would false-alarm
  every Monday. A stalled feed or a moved column is caught by the weekly assumption gate instead.
- `scripts/data/policy.py`: policy candidates from two asymmetric sources, normalized to ONE shape
  (`{id, url, title, abstract, status, effective_date, published, source}`) so the prefilter, sort,
  dedupe and prompt only ever know about one thing. Federal Register is the daily backbone and a
  failed **or zero-result** fetch marks the section unavailable — zero results across 6 agencies and
  45 days is a drifted query, not a quiet day (the Nasdaq-100 class, where a healthy 200 hid dead
  data for 22 days). Utah is seasonal (general session Jan–Mar) and its failures never touch
  availability. The Utah harvest is annual, gated on `UTAH_MIN_SIGNED` and title-prefiltered, and
  queues STUBS only — bill detail pages are fetched lazily at release, at most `MAX_POLICY_ITEMS`
  per run, because harvesting 491 bills eagerly would be ~491 sequential requests inside a
  10-minute job. Utah bills carry the **effective date published in the passed-bills table's own
  "Effective Date" column** (measured live 2026-08-04: 495/495 rows of 2026GS, 550/550 of 2025GS,
  547/547 of 2024GS). It is read at the column position derived from the table's HEADER, never a
  hardcoded index, so an inserted column yields no date rather than silently promoting the passed
  date into the effective date; gate 07's A6 is the fail-closed guard on the column going dark.
  Nothing is derived from the passage date or from Utah's 60-days-after-sine-die statutory default —
  where that default applies, Utah already prints the resolved date (368 of 491 signed 2026GS bills
  read 05/06/2026). The per-bill JSON has no effective-date field at all, so the list page is the
  only source, and three legs must all preserve it: the harvest puts it on the stub, `requeue_utah()`
  carries it back, and `_backfill_utah_dates()` repairs stubs queued before the field existed (that
  third leg is not optional — the live queue already had its session stamped and 14/14 dateless
  stubs, so without it the feature would have been dead until the 2027 session).
  `get_policy()` never raises and writes no state itself; it returns a new state dict.
- `scripts/data/retry.py`: bounded retry for the policy + PMMS HTTP legs, applied inside
  `policy._get()` (so every policy request inherits it) and around `mortgage._fetch()`. At most 3
  attempts with a 2s then 5s backoff, and **transient classes only**: 403/408/425/429, every 5xx,
  timeouts, connection resets and a body that ends mid-stream. **400 and 404 are deliberately never
  retried** — a misspelled Federal Register agency slug returns 400, and that loud failure is a
  property the design depends on; so are non-transport errors (a zero-result `ValueError`, a JSON
  decode error, the PMMS read-cap `ValueError`), because a second identical response cannot change
  a decision about a response that already arrived. Anything the classifier does not positively
  recognise is treated as permanent and re-raised. EXTRA attempts are capped for the whole process
  at `RETRY_EXTRA_ATTEMPT_BUDGET` (4), which is what bounds worst-case ADDED wall time to
  4 x `POLICY_TIMEOUT` + 14s of backoff = **114s**, under 20% of `briefing.yml`'s 600s cap, across a
  retried surface of up to 12 requests. Every retry prints its reason, so a rate-limit episode is
  legible in the job log instead of showing up as a section that quietly rendered nothing.
  The module has a SECOND, unrelated entry point below its "static policy calendar" header:
  `upcoming_calendar(today, horizon_days)`, which shares nothing with the fetch surface — no network,
  no state, no model, no seen set, no effect on `available`. It resolves each `config.POLICY_CALENDAR`
  month/day rule forward against the run date and returns the ones inside
  `POLICY_CALENDAR_HORIZON_DAYS` (30), soonest first. It lives here because it is the same domain and
  the same caller; a separate module for one pure function would add an import for no boundary.
- `scripts/data/constituents.py`: current S&P 500 (~503, linked ticker cell) and Nasdaq-100
  (~101, plain-text ticker cell) member lists from Wikipedia. stdlib regex parse, fail-closed on
  implausible counts — a biased breadth number must never ship silently.
- `scripts/breadth/percent_above_ma.py`: % of index members above their 200-day MA. ONE daily
  POST to TradingView's scanner (top `BREADTH_SCAN_LIMIT` US common stocks; the `type=stock`
  filter is load-bearing — without it ADR/fund rows displace ~90 S&P names), intersected with
  both constituent lists. Per-index `MIN_MATCH` gates. Validated vs published $S5TH / $NDTH.
- `scripts/tts.py`: the audio edition. Composes a deterministic narration (must-knows; S&P/Nasdaq
  percent moves; the 10-year, the 30-year mortgage and the VIX, each followed by the reason the
  page gives for it, then the overall market "why"; the weekly policy digest on Mondays; tech;
  world) and synthesizes it with Gemini TTS (`TTS_MODEL`/`TTS_VOICE`), encoding mp3 in-process with
  `lameenc` (the runner has no ffmpeg). Non-fatal end to end. Still leaner than the page — breadth
  and the policy calendar are page-only — and a story filed in BOTH tech and world is read once
  (`_dedupe_across`, content-word overlap). Mirror narration changes in `docs/app.js`
  `speechText()`; `12-narration-mirror.py` fails the build if the two ever disagree.
- `scripts/data/twelvedata.py`: a REST client. NOT used (v2 breadth shipped keyless via
  TradingView instead). Kept only as a possible future source.
- `scripts/summarize.py`: Gemini call with a response schema. Numbers are passed as facts and the
  model writes only the prose. URLs are validated against the fetched set. `_clean_tldr` drops
  TL;DR fragments (keeps complete sentences) so a malformed model response cannot ship a broken
  headline. Model and no-AI fallbacks. Returns (narrative, ok).
  `summarize_policy()` is a SECOND, independent call for the policy section. The model returns three
  fields and no others — two prose lines plus a copied citation (`what_happened`, `effect`, `url`);
  `status`, `effective_date` and `source` are joined in code from the fetched document. It runs ONE model with no fallback loop at a 60s timeout
  (summarize() loops two models at 120s each — losing the narrative loses the briefing, whereas an
  overrun policy call would cancel the whole job), and returns `([], False)` on any exception.
  `_validate_policy_items()` drops off-set citations, off-host URLs, empty `effect` lines and any
  `$`/`%` figure absent from the source text — each with its own logged reason, because "the model
  rejected everything" (healthy) and "the validator ate everything" (a broken join) are otherwise
  indistinguishable in the job log.
- `scripts/state.py`: load and save `state/state.json` (`last_run`, `markets_last_ok`,
  `markets_first_bad`, per-index `breadth` alert state, `breadth_last_good` cache, and the policy
  keys). `last_run` is always rewritten; `markets_last_ok` advances only on a day all four market
  numbers are present; `markets_first_bad` anchors a blackout that began with no usable healthy
  baseline. `eval_breadth_alert` implements the two alert tiers per index: WARNING one-shot on
  falling below `BREADTH_WARN` (40, re-armed at 42) and OVERSOLD daily nag below
  `BREADTH_OVERSOLD` (30, clears at 33, EXTREME below 20) — both freshness-gated; oversold
  supersedes warning. `record_policy()` is the single writer of `policy_seen` / `policy_active` /
  `policy_today`, and `eval_policy_alert()` flips only the `policy_today.alerted` stamp.
  `record_lesson()` is the single writer of `lessons_taught` (and `forget_lessons()` its only
  eraser, used when a deck write failed and the lesson was therefore never published). Every key,
  its writer and its lifecycle are tabulated in `operations.md`.
- `scripts/notify.py`: ntfy publish for the ready push, breadth alerts, policy alerts, and health
  pings. Also a CLI (`python -m scripts.notify ready`) the workflow calls AFTER `git push` succeeds,
  reading the headline the build wrote to `headline.txt` — so "ready" can never precede publication.

## Key design decisions

- Numbers come from data feeds, never from the model. The model explains them, it does not produce
  them. This is the accuracy guarantee. It holds hardest in the policy section, where a wrong figure
  costs real money: `PolicyItem` has three prose fields and no others, so a status, an effective date
  and a source name are structurally impossible for the model to author — they are joined in code
  from the fetched document, matched by URL. An invented dollar amount is also catchable (`_MONEY`
  compares the item's figures against the source's, after normalizing both sides so `$1,200.00` in
  the source accepts `$1,200` in the output); a hallucinated effective date would not be, which is
  exactly why the model is never asked for one.
- **Owen's Alphabet Soup fetches its source BEFORE it writes.** It is the only section whose subject
  matter has no feed behind it, which makes it the only place a model could write purely from memory
  with nothing downstream to notice. So the order is inverted from how a "daily fact" feature is
  normally built: a topic call proposes exact article titles and NO prose, a real Wikipedia article
  is fetched (no article, no lesson that day), and only then is the lesson written with that text in
  front of the model — after which `_validate_lesson` compares the prose back against the same text.
  The guards are deliberately the policy section's, extended: an invented dollar amount, percentage
  **or year** discards the whole lesson, and so does anything shaped like a drug dosage, whatever the
  article says. The citation is re-taken from the fetch, never echoed from the model.
- **The lesson pointer is client-side, and that is the feature, not a shortcut.** The build publishes
  an append-only deck; the phone decides which entry is current and advances only when the audio
  queue genuinely ended or the reader tapped "New lesson". Nothing on the server may key a lesson to
  a date, which is why the deck is a separate file from `briefing.json` and why a lesson never enters
  the archive. The consequence to preserve: a briefing that was not finished leaves the same lesson
  in place tomorrow. `11-client-pointer.js` is the regression net, because no server-side check in
  this repo can see that rule break.
- Source links are validated in code. Any item URL not in the fetched article set is dropped, so an
  invented citation cannot reach the output. Policy items additionally pass a two-host allowlist
  (`www.federalregister.gov`, `le.utah.gov`), and the rendered `url` is re-taken from the candidate
  rather than echoed from the model — URL matching tolerates a trailing slash, but the client renders
  the field as an href and `.../HB0068.html/` is a 404.
- The policy section reports only what changes a number, a deadline, or an obligation for one
  specific reader. That is a narrow, effect-tested exception to the "no granular US politics" rule in
  `summarize.SYSTEM`, not a reversal of it: importance in general is explicitly not a criterion. A
  cheap word-boundary keyword prefilter runs before the model and the call is skipped entirely when
  nothing survives it.
- **The model ranks; it does not judge in isolation.** The `policy_seen` dedupe runs AFTER selection,
  not before the prompt, so `get_policy()` hands over the whole prefiltered window (~9-12 documents)
  every day. This is the 2026-08-03 reversal of the original design and it was measured, not
  reasoned: given ONE on-profile document alone the model returned nothing, while ranking a batch of
  26 in the same run it selected correctly (CI run 30851392524). The old design's own success
  condition — a small unseen set — was what put the model in its failing mode. The cost is a Gemini
  call on most mornings instead of ~3 a month; a dozen 500-character documents is trivial beside the
  two calls the briefing already makes. Test 06's **G8** calls `get_policy()` twice and goes red if
  the input ever shrinks because of the seen set.
- An empty policy section is a correct outcome, not a failure. It renders nothing rather than
  "Information not available." (that message would be a lie), and `data_availability.policy` tracks
  the FETCH, not the item count — deriving availability from an empty list would flag every healthy
  quiet day as degraded.
- **The static calendar is hardcoded because there is nothing to poll, and it cannot go stale
  because no entry carries a year.** The annual figures this reader most wants — the conforming loan
  limit, the IRS brackets and standard deduction, the retirement contribution limits, the ACA
  enrollment window — are not in the Federal Register at any document type and have no
  machine-readable feed (measured; see `integrations.md`). So the fetched half of this section can
  only ever REACT to rulemaking, and the calendar is the only mechanism available for the rest. Three
  properties make hardcoding safe, and `09-policy-calendar.py` is the machine that keeps them true:
  every entry is a month/day RULE resolved forward (so it rolls into next year the day after it
  passes, and can never render a past date under "What's coming"); every label is ANTICIPATORY
  ("expected late November", never "November 25" — the same rule as the model never authoring a
  figure, applied to dates); and each anchor is the END of the plausible window, so an entry stays
  visible for the whole period the event could land in. The horizon is 30 days on purpose: eight
  events a year put the block on screen ~44% of mornings, which keeps the section intermittent
  rather than silently converting it into an always-on one.
- The calendar is emitted **outside** `_get_policy()`. Routing static facts through the function that
  owns the model call, the seen set and the push is what would let them drift into being summarized,
  recorded or alerted on. It is the `_facts_block()` principle at section scale: values the model
  never touches do not travel through the model's plumbing.
- The run degrades, it does not skip. A failed feed marks one section unavailable. A failed AI call
  falls back to a no-prose briefing of raw numbers and headlines. World news always ships if present.
- Staleness is age-based. The PWA shows a notice when the briefing is older than `STALE_HOURS`.
- The daily commit always changes `state.json` (last_run), which keeps the scheduled workflow from
  auto-disabling after 60 idle days.
- The archive needs an index. GitHub Pages cannot list a directory, so the pipeline writes
  `docs/archive/index.json` for the PWA to read.
- Fail-closed over plausible-but-wrong. Breadth refuses to publish when constituent matching
  drops below MIN_MATCH (scan/shape drift); the audio manifest is written only alongside a real
  mp3 so the player can never bind stale audio to a new page; the "ready" push fires only after
  the publish leg succeeded; a Federal Register query that returns zero results is treated as broken
  rather than quiet; a PMMS body that hits the read cap is discarded rather than parsed, because a
  truncated CSV row still parses — as a wrong rate.
- Already-published output is never re-derived. `_write()` rewrites `docs/briefing.json` AND
  `docs/archive/<date>.json` unconditionally, and `briefing.yml` dispatches with `--force` defaulting
  to true, so a second run of the day is the normal manual path. The policy leg therefore checks
  `state.policy_today` and re-emits verbatim BEFORE touching the network: a re-fetch that went badly
  would otherwise overwrite the archive with an empty list and delete items already sent to the user.
- A transient model failure must not bury a day's candidates. Nothing is marked `policy_seen` unless
  `summarize_policy()` returned ok — a Gemini outage retries tomorrow instead of silently consuming
  the day. And `policy_seen` now records only what was actually REPORTED (plus the first-run
  bootstrap window, which is marked seen precisely because it is being withheld), because the seen
  set is no longer an input filter: recording everything sent would bury the whole window after one
  call. A candidate the model never selects therefore comes back tomorrow rather than being buried
  unread. (Two earlier revisions of this feature shipped a policy state field that was declared and
  read but never written; routing all three keys through `record_policy()` is the structural fix.)
- Rendering the policy section is guarded at the call site. `policySection()` returns null when
  nothing qualified and `appendChild(null)` throws — and a throw inside `render()` is worse than a
  blank page: `loadBriefing()` has already committed the sequence and advanced `lastGeneratedAt`, so
  the page is left half-built with no error message and the visibilitychange refetch skips
  re-rendering for the rest of the session.
- Recurring silent bug-classes get machine guards, not comments: `shell-guard.yml` fails a shell
  change without a sw.js CACHE bump (this class shipped broken once); workflows install with a
  CI-frozen `constraints.txt` and pin actions by commit SHA (the daily job holds a write token).
- Failures must be loud, not silent. Four independent monitors cover the failure classes that have
  actually occurred: the build's own crash/degraded ntfy; a sustained market blackout escalating to
  high-priority after `MARKETS_STALE_DAYS` (a dead source degrades silently otherwise); an
  independent heartbeat workflow checking the live page (catches a build that stopped or no-opped);
  and, since 2026-08-03, a WEEKLY `data-smoke.yml` that re-proves every upstream shape from a runner
  and pushes ntfy when one goes red. That fourth one exists because a guard nobody triggers is not a
  guard: the Nasdaq-100 test detected Wikipedia's table move correctly and the breakage still lasted
  22 days, because the workflow was dispatch-only and no one dispatched it.

## briefing.json schema

```
generated_at : ISO datetime (America/Denver)
date         : YYYY-MM-DD
tldr         : list of up to 3 strings
market       : { sp500: {value, change, asof}, ndx: {value, change, asof}, why: str }
yield_10y    : { value, change, asof, why }
vix          : { value, change, asof, why }
breadth      : { sp500: B, ndx100: B } where B = { value, asof, status, matched, stale }
               (status: oversold <30 | watch <40 | healthy >=40 | unavailable; value null when
               unavailable; stale=true when served from the last-good cache. Archives before
               2026-07-06 carry a legacy flat single-index shape, which the PWA still renders.)
mortgage     : { value, change, asof } or null — the 30-year fixed PMMS rate, rendered as a 5th
               market tile. `change` is the week-over-week move in percentage points, shown as bps
               (+8 bps); null when no prior release row exists, never a fabricated 0.
policy       : list of { what_happened, effect, url, status, effective_date, source }
               (status: "Final rule" | "Proposed" | "Signed in Utah"; effective_date is legitimately
               null on proposed rules; on Utah bills it is the legislature's own published
               effective date. Usually [] — that is the normal quiet day.)
policy_upcoming : list of already-reported items whose effective_date is still ahead, same shape,
               capped at MAX_POLICY_UPCOMING (5), sorted by date ascending. Carries `effect` too:
               the carry exists so a deadline stays meaningful rather than becoming a bare headline.
policy_calendar : list of { date, label, note, url } — recurring annual events from
               config.POLICY_CALENDAR whose next occurrence is within POLICY_CALENDAR_HORIZON_DAYS
               (30), soonest first. Deliberately DISJOINT key names from a reported item: these two
               look alike on screen and mean opposite things (something that HAPPENED with a
               published effective date vs something merely EXPECTED), and disjoint keys mean neither
               can ever be rendered, validated or recorded as the other. `date` is the resolved
               anchor and is used ONLY for ordering — the client never prints it, because the
               precision is not real; the timing lives in the label's words. No model involvement of
               any kind, and no entry in `data_availability`: it cannot fail.
tech         : list of { summary, source, url }
world        : list of { summary, source, url }
weekly_recap : string or null (Sundays only)
data_availability : map of section -> true/false or "ok"/"unavailable"
                    (adds `policy` — the FETCH's result, true on a re-emit and on a quiet day — and
                    `mortgage`. Neither joins the `markets_ok` tuple: PMMS is a weekly release, so a
                    normal publishing gap must not fire the high-priority market-blackout page.)
```

Archived briefings written before the policy section shipped carry no `mortgage`, `policy`,
`policy_upcoming` or `policy_calendar` keys. The PWA renders them unchanged: the mortgage tile is
appended only `if (b.mortgage)`, and `policySection()` treats each missing list as empty and returns
null when all three are empty.

Companion files: `docs/briefing-audio.mp3` (the day's narration) + `docs/briefing-audio.json`
(`{date}` manifest — the player binds audio only when it matches the briefing's date).

## lessons.json schema (Owen's Alphabet Soup)

Published separately from `briefing.json` and deliberately NOT part of it or of the archive: a
lesson belongs to the deck, not to a date, and an archived edition is a record of one day's news.

```
generated_at : ISO datetime of the last build that touched the deck
outro        : path to the shared sign-off clip ("lessons/outro.mp3"), generated once and reused
lessons      : append-only, oldest first, pruned to LESSON_DECK_MAX (60). Each entry:
  id            : "<date>-<article-slug>"; also the audio filename stem and the client's pointer key
  date          : the day the lesson was WRITTEN (not the day it is read)
  domain        : one of config.LESSON_DOMAINS, rotated evenly by lessons-taught count
  title, hook   : the headline and the one-sentence "why this matters"
  quick         : the core lesson. Stands alone — many days it is the only tier read
  more, deep    : cumulative extensions, each continuing where the last stopped
  takeaway      : the one concrete action. Rendered and SPOKEN right after `quick`, because `quick`
                  is a complete lesson and the deeper tiers are extensions after it
  source        : { title, url } — joined in code from the fetched article, never from the model
  audio         : { tier: path } for the clips that actually wrote. May be {} (a failed TTS day, or
                  a lesson older than LESSON_AUDIO_RETAIN, whose clips have been pruned). The prose
                  above is why that degrades to the device voice instead of to silence.
```

**What is NOT in this file, or in `state.json`, is the point of the feature:** which lesson is
current. That pointer lives in the browser's `localStorage` under `soup.v1`
(`{length, completed[], skipped[]}`), because it advances on exactly two events — the audio queue
reached its end, or the reader tapped "New lesson" — and both are facts only the device can observe.
A server-side "lesson of the day" would be a guess at a client-side fact, and would break the one
rule the feature exists for: an unfinished lesson is still there tomorrow.

Note: `market.ndx` is the Nasdaq Composite (Yahoo `^IXIC`), labeled "Nasdaq" in the UI. Each
number carries its own `asof` date. Values are the latest SETTLED daily close — a bar belonging to
a still-open session is dropped, never shipped as a close. `change` is the difference of the last
two settled closes, or `null` when only one settled close is available (the UI then shows the
level alone; the AI facts block says "change unavailable"). The UI shows the as-of date and the AI
describes the figures as the latest close.

## Entry points

- `python -m scripts.build_briefing` runs the daily flow with the once-per-day date-gate.
- `--force` bypasses the date-gate and builds now (manual CI run).
- `--local` bypasses the date-gate and builds now (dev).
- `--spine` prints market numbers, news counts, breadth, and a federal policy-candidate count;
  writes nothing. The policy line deliberately calls `policy._federal_candidates()` directly rather
  than `get_policy()`: the full entry point would run the annual 491-row Utah scrape plus detail
  fetches and touch state, and `data-smoke.yml` greps this output under a job timeout.
- `--no-notify` skips the ntfy pushes.
- `python -m scripts.heartbeat` checks the live page freshness (run by its own workflow).
- `python -m scripts.notify ready` sends the post-publish ready push (workflow-only step).

## Scope

v1 (core briefing) and v2 (breadth + tiered oversold alerts, both indices; audio edition) are
built and live. The delivered v2 design (with deltas from the original plan) is archived at
`tmp/done-plans/2026-06-16-breadth-and-fresh-data.md`.

v3 adds "Policy that affects you" and the 30-year mortgage tile. One known gap is deliberate; a
second that was listed here has since been closed:

- ~~**No forward-looking calendar.**~~ **CLOSED 2026-08-03.** `policy_upcoming` can only ever contain
  items that were already reported, so the section was absent most mornings and carried nothing
  anticipatory. `config.POLICY_CALENDAR` + `policy.upcoming_calendar()` now supply eight recurring
  annual events — exactly the announcements that have no feed to watch — rendered inside "What's
  coming" and visually separated from reported items. The reason it was cut from the plan ("no shape,
  no source, no staleness story") is answered by a shape (month/day rules carrying no years), sources
  (a probed `.gov` URL and a sourcing note per entry) and a staleness story that is a runnable gate,
  `09-policy-calendar.py`, rather than a paragraph.
- **The audio edition reads policy once a week, not daily.** Adding a fourth topic to every
  morning's script was not worth the length, so the digest rides `config.POLICY_AUDIO_WEEKDAY`
  (Monday) and covers the whole week via `state.policy_week` — reading only that morning's `policy`
  key would silently drop everything found on the other six days. Breadth and the policy calendar
  stay page-only.

v4 adds **Owen's Alphabet Soup**: one grounded lesson a day, rendered last on the page and played
last in the audio, advancing only when the briefing is actually finished or the reader asks for a
new one. Known limits, all deliberate:

- **One new lesson a day (two on the very first run).** The "New lesson" button can therefore run
  out, and says so rather than inventing something. The reader's own unfinished lessons are the
  buffer, which is the same property the completion rule creates.
- **Lesson audio is kept for the last `LESSON_AUDIO_RETAIN` (21) lessons only.** Raised from 10 on
  2026-08-20: the old value was justified by "every daily commit is permanent git history", which is
  true of CREATING a clip and not of KEEPING it — the blob is in history from the commit that added
  it, so pruning reclaims checkout bytes and never shrinks the repo. Since the pointer serves the
  OLDEST unfinished lesson, a 10-lesson window meant a reader two weeks behind met the device voice
  on every lesson they were behind by. A pointer that still falls off the window works — the deck
  carries the prose, and the device voice reads it.
- **Missing lesson clips are repaired, not written off.** `tts.backfill_lesson_audio()` re-synthesizes
  up to `LESSON_AUDIO_BACKFILL_MAX` (2) missing clips per run for lessons inside the retention
  window, oldest first, and `_synthesize()` retries transient TTS failures. Before both existed a
  single 429 lost a tier permanently, because `generate_lesson_audio()` only ever ran for the entries
  created that morning.
- **Wikipedia is the only source.** It is keyless, has plain-text extracts, and covers all four
  subject areas with the mechanics a lesson needs. A `.gov`-style primary source would be better for
  the money and health domains, but none of them publishes a machine-readable article API — the same
  finding that produced `POLICY_CALENDAR`.

One residual risk was found by the weekly gate and has been fixed by removing the mode rather than
prompting around it. The model's selectivity was proven on a batch of 24 candidates, where it could
rank documents against each other; with the old pre-prompt `policy_seen` differencing, production
usually sent it one or two. Test 06's **G8** probed that seam with one-document model calls and went
RED on CI run 30851392524: given a single on-profile document (2026-13286) the model returned
nothing, while in the same run it correctly picked 2 of 26 from the batch. "Is this one thing
relevant?" really is a different question from "pick the best of these 26".

The fix (2026-08-03) makes the batch the only mode production ever uses:

- `policy.get_policy()` sends the full prefiltered window, already-reported ids included.
- `summarize_policy()` asks for `MAX_POLICY_SELECTIONS` (6) ranked items instead of 3, so a new item
  can still survive when the top of the list is old news.
- `build_briefing._new_policy_items()` drops already-reported ids and then cuts to
  `MAX_POLICY_ITEMS` (3).
- `policy_seen` consequently records only what was REPORTED.

**G8 was not deleted and is not left red.** It now asserts the invariant the fix depends on — two
calls to `get_policy()`, the second with every returned id marked seen, and no candidate may
disappear — with `POLICY_SEEN_CONTROL=true` as its negative control. The one-document calls survive
as a recorded MEASUREMENT (`single_candidate_probe.single_candidate_selects` in the fingerprint,
printed as a NOTE) because the limitation is real and worth tracking. **The model did not get
better**: a future run where the measurement reads `true` is not permission to move the dedupe back
in front of the prompt.
