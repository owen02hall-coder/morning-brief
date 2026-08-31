---
title: Operations
source_files: [.github/workflows/, scripts/build_briefing.py, scripts/heartbeat.py, scripts/notify.py, scripts/briefing-assumptions/]
entry_points: [".github/workflows/briefing.yml", ".github/workflows/heartbeat.yml", ".github/workflows/shell-guard.yml", ".github/workflows/data-smoke.yml", ".github/workflows/guard-triggers.yml", "scripts/build_briefing.py:main", "scripts/heartbeat.py:main"]
last_verified: 2026-08-11
---

# Operations

How the briefing is scheduled, deployed, monitored, and recovered.

## Schedule

- Defined in `.github/workflows/briefing.yml` with two cron entries: `0 12 * * *` and `0 13 * * *`
  (UTC). GitHub cron is UTC only.
- 6am America/Denver is 12:00 UTC during daylight time and 13:00 UTC during standard time. Both
  crons fire. The script de-dupes by date (`state.last_run`): whichever cron lands first that day
  does real work, the rest see `last_run == today` and no-op. There is no hour comparison.
- The date stamp uses `zoneinfo("America/Denver")` via `_now()`, which needs the `tzdata` package
  (in requirements.txt).
- Scheduled runs can be delayed at peak load by GitHub — often by hours. The date-gate is built for
  exactly that: delay no longer prevents the day's build (an earlier hour-gate did, freezing the
  briefing for days). Do not reintroduce an exact-hour gate.

## Deployment (one-time)

1. Create a public GitHub repo and push this code. Public is required for free Pages and unlimited
   Actions minutes. The page is world-readable and contains only public news.
2. Repo Settings, Pages: Source "Deploy from a branch", branch `main`, folder `/docs`.
3. Repo Settings, Secrets and variables, Actions. Names must match what `briefing.yml` /
   `heartbeat.yml` reference (the workflows map the GitHub names into the env vars the code reads):
   - Secret `GEMINI_API_KEY` (read as `GEMINI_API_KEY`)
   - Secret `NTFY_SUB` (mapped to the `NTFY_TOPIC` env var the code reads)
   - Variable `PAGE_URL` set to the Pages URL (mapped to the `PAGES_URL` env var)
   - A name mismatch here is silent: a missing `NTFY_TOPIC` just skips every push, and a missing
     `PAGES_URL` falls back to a placeholder. If you rename a secret/var, update both workflows.
4. Install the ntfy app on the phone and subscribe to the same topic.
5. Actions tab, run the workflow once with "force" on. Then open the Pages URL on the phone and use
   Add to Home Screen.
6. The heartbeat workflow needs no extra setup; it reuses the same `NTFY_SUB` secret and `PAGE_URL`
   variable and starts its schedule once it is on the default branch.

## Runtime behavior

- Entry point: `python -m scripts.build_briefing`.
- Step order matters: the job fails fast if `NTFY_SUB` is empty (all alerting would be silent),
  installs `requirements.txt` with `-c constraints.txt` (CI-frozen transitive lock), runs the
  build (which also writes `headline.txt` and, on TTS success, `audio.mp3`), publishes the audio
  edition into `docs/` (manifest written only alongside a real mp3), commits `docs/` + `state/`
  and pushes (with a rebase-retry so a human push to main mid-run can't kill the day), and ONLY
  THEN sends the "ready" push via `python -m scripts.notify ready`. A failed publish can never
  follow a delivered "ready".
- The commit always changes `state.json` (last_run), so there is a daily renewing commit even on
  market holidays. This prevents the 60-day scheduled-workflow auto-disable.
- `permissions: contents: write` lets the token push. No personal access token is used, so the push
  does not retrigger the workflow (but it DOES trigger `shell-guard.yml`, which no-ops unless PWA
  shell files changed).
- `timeout-minutes: 10` bounds the job; the failure backstop fires on `failure() || cancelled()`
  so a timeout-kill still alerts. That budget is the reason every policy-leg bound exists: each
  request carries `POLICY_TIMEOUT` (25s) and a byte cap, the second Gemini call uses a 60s timeout
  with no fallback loop, the Utah harvest fetches no bill pages at all, and the release path fetches
  at most `MAX_POLICY_ITEMS` (3) of them per run. A cancelled job ships no briefing AND pages
  high-priority, so an overrun is strictly worse than a missing section.
- Actions are pinned by commit SHA; bump deliberately (look up the new tag's SHA, update all
  workflows, validate with a Data Smoke run).

## Monitoring

- Morning push: a "ready" ntfy is sent on a successful run, tapping through to the page.
- Health ping: if any section is unavailable, a low-priority "degraded" ntfy lists the sections. If
  the run crashes, the Python layer sends a high-priority "FAILED" ntfy. A workflow `if: failure()`
  step sends a backstop ntfy in case the crash happens before Python can.
  - This ping names a SECTION, not a cause, and that is its limit. On 2026-08-31 it correctly said
    `degraded sections: alphabet soup` for days while the actual fault was a throttled Wikipedia
    User-Agent. When one arrives, go to the run log and read the leg: `gh run view <id> --log`.
- Monitoring gap (`notify.monitoring`, normal priority): a SEPARATE title from the health ping,
  because the two say opposite things about the morning. "Briefing degraded" means a section is
  missing from the edition about to be read; "Monitoring gap" means the edition is fine but
  something has stopped watching for the next failure. Titling the second one like the first would
  send the reader hunting for a problem that is not in the briefing.
- Market blackout escalation: the build tracks `markets_last_ok` in `state.json`. A single day with
  all four numbers missing is a low-priority "degraded" ping, but once they've been unavailable for
  `MARKETS_STALE_DAYS` (2) days running — a dead source, not a blip — it escalates to a high-priority
  ntfy. This exists because the prior source (FRED) died silently and degraded for days unnoticed.
  When no usable `markets_last_ok` baseline exists (fresh deployment / reset state), the build
  anchors `markets_first_bad` instead, so a source that has never been healthy escalates on the
  same schedule rather than degrading silently forever.
- Heartbeat: an independent workflow (`.github/workflows/heartbeat.yml`, daily at 03:00 UTC) fetches
  the LIVE Pages `briefing.json` and, if it is older than `HEARTBEAT_STALE_HOURS` (30h) or
  unreachable, sends a high-priority ntfy AND fails the job (so its own `if: failure()` curl fires
  as a second alarm leg — independent of the Python process, though every alarm leg still terminates
  at the same ntfy topic, an accepted v1 trade-off). Because it runs on its own schedule and checks
  the real page, it catches both a build that silently no-ops and a build cron that GitHub dropped
  entirely.
  - It also WATCHES THE WATCHDOG. A red Data Smoke pages; a Data Smoke that never runs is silent,
    and that is the same shape as the 22-day breadth outage. The heartbeat reads data-smoke.yml's
    run history and sends a "Monitoring gap" ntfy past `SMOKE_STALE_DAYS` (9 — a weekly cron plus a
    day of GitHub scheduling slop). It counts `event=schedule` runs ONLY: a manual dispatch proves
    the tests pass, not that the trigger still fires, and the trigger is what goes missing. Needs
    `actions: read` on the job. An unreachable API returns "unknown", which is deliberately NOT an
    alert — the check runs daily against a 9-day threshold, so eight more attempts land before the
    answer could matter, and a persistent failure still surfaces when the clock runs out. It never
    exits non-zero, so a stale smoke schedule cannot masquerade as "Heartbeat FAILED".
- Breadth alerts (per index, S&P 500 and Nasdaq-100): a one-shot normal-priority warning when
  breadth falls below 40% (re-armed only after recovering to 42), and a high-priority daily nag
  below 30% with a day counter (clears at 33, EXTREME below 20). Both suppressed on stale data.
- Policy push: one normal-priority ntfy per newly-reported FINAL rule ("Policy that affects you").
  Proposed rules and queue-released Utah bills never push. The `policy_today.alerted` stamp makes it
  one-shot per date, which matters because `briefing.yml` dispatches with `force` defaulting to true,
  so a same-date rerun is the normal manual path and must not re-push.
- Shell guard: `shell-guard.yml` fails any push that changes `docs/` shell files without bumping
  the sw.js CACHE constant, and ntfy-pages on trip — installed PWAs would otherwise silently
  never update (this class shipped broken once).
- Data smoke: `data-smoke.yml` runs WEEKLY (`0 16 * * 1`, Mondays ~10am Denver) as well as on
  dispatch. It prints the data spine from a runner and fails if either index's breadth doesn't
  compute, then runs assumption tests 04, 05, 06, 07, 08, 09, 10, 11, 12, 13 and 14 — the RSS feeds
  and constituent tables, Federal Register, PMMS, the Utah list page, Utah bill detail pages, the
  keyword prefilter, the policy calendar, the lesson sources and Wikipedia User-Agent, the client
  pointer, the narration mirror, and two real model calls. Each step is `if: always()` so one dead
  leg cannot mask the others (on 2026-08-03 a failed spine step skipped the policy check entirely
  and hid whether `.gov` egress worked at all); the job still goes red if any step fails.
  - **The page is GRADED by what broke** (since 2026-08-31). Every step carries an `id:`, and the
    alert splits them: SOURCE steps (feeds, scrapes, fetches, deterministic rules) page HIGH and are
    NAMED in the message; JUDGMENT steps — the two live model calls, 06 and 13 — page LOW as "a
    judgment test flapped", because they are scored against whatever the world published that day
    and they flap. Before this, every red run sent one high-priority "a data leg went red" whatever
    had happened: it fired for a transient Gemini 5xx on 08-17 and for a live news item containing
    the word "Republican" on 08-31. A pager that cannot tell a dead source from a model having an
    opinion is one you learn to swipe away, and the alert it has to survive is the 22-day kind.
  - The RUN still goes red for either class, deliberately — no `continue-on-error`. A green check
    over a failed assertion is how a guard rots; the run is the durable record. Only the
    interruption is graded. A red run where NO known step reported failure (a cancel, a timeout, or
    a new step missing from the alert's list) pages HIGH and says exactly that rather than guessing.
  - **Every assumption test must be RUN by something** — `guard-triggers.yml` (push/PR, offline,
    seconds) fails the push if an `NN-`named test is invoked by no workflow and is not on its
    documented exclusion list. The class shipped twice: 04 caught the Nasdaq-100 drift and nobody
    ran it for 22 days, then the 08-03 fix wired up every OTHER test and still left 04 out until
    2026-08-31, when its own fingerprint showed it had last run on 08-04. An unwired test does not
    error or warn — it simply never runs, while a directory of green-looking guards implies coverage
    that does not exist. A mention in a comment does not count as wired; the check requires a real
    `python`/`node` invocation of the path. The exclusion list fails closed both ways: a ghost entry
    would pre-approve a future test reusing the name, and a test both wired and excluded means its
    written reason is now fiction. Currently excluded: 01 and 02 (metered Twelve Data quota, staged
    path) and 03 (Gemini quota; its subject is covered transitively by 06 and 13).
  - The schedule is the point, not a convenience. This workflow was dispatch-only until 2026-08-03,
    and that is exactly why Nasdaq-100 breadth stayed dead for 22 days: the guard existed, the
    trigger did not, and a scheduled failure only emails the repo owner — the channel that gets
    ignored. Weekly rather than daily because these are slow-moving upstream shapes and a red run
    must stay a real signal.
  - Two traps that would silently disarm it, both already handled: the alert step must be
    `if: failure() || cancelled()`, because a `timeout-minutes` kill is a CANCELLATION and
    `failure()` alone misses the slowest failure mode; and the env mapping must be
    `NTFY_TOPIC: ${{ secrets.NTFY_SUB }}` — `secrets.NTFY_TOPIC` does not exist, would resolve to
    empty, and the step's `[ -n "$NTFY_TOPIC" ]` guard would skip without a word.
  - `PYTHONPATH: ${{ github.workspace }}` is set on the assumption-test steps so they can
    `from scripts import config` and prove the PRODUCTION query shape rather than a drifting local
    copy. `python -m` cannot address these files (leading digits, hyphens, no `__init__.py`), so the
    import path is the only route.
  - `timeout-minutes: 10`, raised from 5 when the three extra tests were added.
- Transparency: `briefing.json` carries a `data_availability` map showing each section's status.

## Run state (`state/state.json`)

Committed to the repo on every run, never served on Pages. `state.save()` always rewrites `last_run`,
which is what guarantees the daily commit that keeps the scheduled workflow alive.

Every key below names its writer. That is not documentation habit, it is a scar: two revisions of the
policy design shipped a state field that was declared and *read* but never written, which produces a
feature that looks healthy and is permanently empty. If a key here cannot name its writer, it does
not exist.

The static policy calendar adds **no key at all**, and that is the design, not an omission: it is
pure — it resolves `config.POLICY_CALENDAR` against the run date on every run — so there is nothing
to remember, nothing to expire and nothing to recover. It also never marks anything seen and never
pushes.

| Key | Written by | Read by | Lifecycle |
| --- | --- | --- | --- |
| `last_run` | `state.save()`, every run | `main()`'s once-per-day gate | Rewritten daily |
| `markets_last_ok` | `run()` on a day all four market numbers are present | the blackout escalation | Advances only on healthy days; clears `markets_first_bad` |
| `markets_first_bad` | `run()` when markets are down and no usable healthy baseline exists | the escalation's "no baseline" branch | Anchors a blackout; removed on the next healthy day |
| `breadth` (per index) | `eval_breadth_alert()` — **only on notifying runs** | itself (`in_alert`, `nag_days`, `warn_armed`) | Latched with hysteresis; a `--local`/`--no-notify` run must not consume an alert it never delivered |
| `breadth_last_good` (per index) | `_get_breadth()`, every run | `_get_breadth()`'s fallback | Served for up to `BREADTH_STALE_TRADING_DAYS`, marked `stale` |
| `policy_seen` `{id: published}` | `record_policy()` — only for items actually REPORTED on a successful model call, plus the first-run bootstrap window | `build_briefing._new_policy_items()` (the post-selection drop) and `policy._maybe_harvest_utah()` | **Never pruned.** ~200 entries a year in a file rewritten daily; an eviction rule interacting with the 45-day fetch window is a hazard for no benefit |
| `policy_active` `[item]` | `record_policy()`, every run | the `policy_upcoming` projection | Deduped by url, sorted by date, capped at `MAX_POLICY_UPCOMING` (5); an entry drops out the day its `effective_date` passes. Utah bills can now reach this list at all — they previously always carried `effective_date: None` |
| `policy_today` `{date, items, alerted}` | `record_policy()` every run; `alerted` flipped by `eval_policy_alert()` on notifying runs | the same-date re-emit branch; the one-shot push | Replaced only when the stored date differs from today |
| `policy_utah_queue` `[stub]` | `policy._maybe_harvest_utah()` appends; `policy._release_utah()` pops; `policy.requeue_utah()` pushes unreported ones back to the front; `policy._backfill_utah_dates()` repairs old entries | the release path | Drains at ≤`MAX_POLICY_ITEMS`/day; stubs are `{id, url, title, effective_date}`, detail text is fetched at release. Stubs queued before `effective_date` existed are repaired ONCE by `_backfill_utah_dates()` (one list request; key PRESENCE, not truthiness, marks a stub handled, so it terminates). Without that the field would stay null on every already-queued bill until the next general session |
| `policy_utah_session` | `policy._maybe_harvest_utah()` — **only** when a harvest yielded ≥`UTAH_MIN_SIGNED` signed bills | the annual harvest gate | Annual. Stamped with the session actually USED, so a prior-year fallback leaves the gate open and the next run retries the real current session |
| `policy_bootstrapped` | `build_briefing._get_policy()` on the first policy run whose FEDERAL fetch succeeded | the bootstrap suppression | Once, ever |
| `lessons_taught` `[{id, article_title, title, domain, date}]` | `state.record_lesson()` when a lesson's prose is written; `state.forget_lessons()` removes entries whose deck write then FAILED | `data/lessons.first_usable()` (the real dedupe, applied after the fetch so redirects collapse), the topic-proposal avoid-list, and the domain rotation index | Capped at 500 (~16 months). The LONG memory: the published deck is pruned to 60, but a lesson repeating a year later is what this prevents |
| `lessons_bootstrapped` | `state.record_lesson()` on the first lesson ever written | `_get_lessons()`'s "two on the first run, one a day after" branch | Once, ever. Means "the first run happened", NOT "a lesson exists" — it is not cleared by `forget_lessons()` |

**The lesson pointer is NOT here, and must never be added.** Which lesson the reader is currently on
lives in the browser's `localStorage` (`soup.v1`), because it advances only when the audio actually
reached the end or the reader tapped "New lesson" — facts the build cannot observe. A "current
lesson" key in this file would be a server-side guess at a client-side fact and would break the rule
the feature exists for: an unfinished lesson is still there tomorrow. `state.json` remembers only
what has been *taught*, never what has been *read*.

Three lifecycle rules are worth stating outright because they are the ones easiest to break:

- **`policy_seen` is written only after `summarize_policy()` returns ok, and only for what was
  REPORTED.** A Gemini outage therefore leaves the day's candidates unseen and tomorrow retries them,
  instead of burying them permanently. "Reported, not sent" is the 2026-08-03 reversal: the seen set
  is no longer an input filter (`get_policy()` hands the model the whole prefiltered window so it is
  always ranking, never judging one document alone), so recording everything sent would bury the
  window after a single call. A candidate the model never picks is re-sent tomorrow — which is
  correct; burying it unread was the old bug.
- **`policy_bootstrapped` is gated on the federal fetch succeeding.** Stamping it after a FAILED
  fetch would mark zero candidates seen and then back-announce the entire 45-day backfill tomorrow —
  the exact opposite of what the suppression exists for. The Utah queue is exempt from the
  suppression entirely: blanket-suppressing run one would swallow the whole queue of a completed
  session (17 of 2026GS's 491 signed bills pass the prefilter) and leave Utah contributing nothing
  until the next general session in March.
- **A lesson is stamped taught when it is WRITTEN, and un-stamped if the deck write then failed.**
  Recording at write time is deliberate: the reader draws from the deck, and re-teaching an article
  because they have not reached the first copy yet is the worse failure. But a lesson that was
  stamped and never published would be an article the reader can never be taught, invisibly — so
  `_publish_lessons()` returns whether the deck landed, and `run()` calls `forget_lessons()` and
  re-saves when it did not.

## Failure modes and recovery

- A dead RSS feed: skipped per-feed. If all world feeds are down, the world section reads
  "information not available" but the briefing still ships.
- Yahoo slow or down: that number degrades to None and shows as unavailable. The client retries and
  tries the query1/query2 hosts, with a short fail-fast timeout so it can't stall the build.
- Gemini down: the model fallback runs, then the no-AI fallback (raw numbers and headlines). The day
  is never skipped.
- A skipped or failed day: the PWA shows an age-based "could not refresh, last updated X" notice
  rather than presenting old data as current.
- A wrong tap-through link: if `PAGES_URL` is still the placeholder, `notify.morning_ready` prints a
  loud warning.
- TradingView scan fails or matches too few constituents: that index's breadth serves the cached
  last-good value (dated, marked stale) for up to 2 trading days, then shows unavailable. The
  briefing still ships; alerts are suppressed on stale values.
- Gemini TTS fails: no manifest is written, the page's Listen button falls back to the on-device
  voice, and the degraded ping includes "audio". The briefing still ships.
- **The Alphabet Soup lesson leg fails** (no proposal, no usable article, a validation rejection, or
  a Gemini outage): the deck simply does not grow that day and the degraded ping lists "alphabet
  soup". The reader notices nothing unless they were already caught up, because their pointer is
  still sitting on whatever they have not finished. Nothing is stamped taught, so tomorrow retries.
  A **same-date rebuild** also produces no lesson and is reported as HEALTHY, not degraded — the leg
  returns an explicit `healthy` flag rather than letting the caller infer it from an empty list,
  which is the same distinction `_get_policy()` draws when it re-emits.
- **Only some lesson clips synthesize** (a per-minute rate limit, or the run passing
  `LESSON_AUDIO_DEADLINE`): the deck entry records exactly the clips that wrote. The client requires
  ALL the clips for the reader's chosen depth before using audio, and otherwise reads that lesson in
  the device voice — one consistent voice rather than a hand-off mid-lesson. This is now SELF-
  HEALING: `_synthesize()` retries a transient failure (`TTS_RETRY_ATTEMPTS`), and every run calls
  `tts.backfill_lesson_audio()`, which re-synthesizes up to `LESSON_AUDIO_BACKFILL_MAX` (2) missing
  clips for lessons still inside the retention window, OLDEST FIRST — the order matters because the
  pointer serves the oldest unfinished lesson, so that is the gap the reader actually hits. Before
  2026-08-20 neither existed: `generate_lesson_audio()` only ever ran for the entries created that
  morning, so one 429 lost a tier for good and parked a device-voice lesson at the head of the deck.
  A backlog of gaps closes over several mornings rather than all at once, by design — the cap keeps
  repair work from crowding out today's own clips or the free tier's daily budget.
- **The reader's pointer falls behind the audio retention window** (`LESSON_AUDIO_RETAIN`, 21
  lessons — raised from 10 on 2026-08-20): the pruned entries keep their prose and lose only their
  `audio` paths, in the same pass that deletes the files, so the deck can never advertise a clip that
  is gone. That lesson is read by the device voice. Three weeks of clips is the window because the
  pointer serves the OLDEST unfinished lesson, so the retention window is really "how far behind a
  reader may fall and still get the good voice".
- **The reader clears site data or gets a new phone:** the pointer is gone, and the deck restarts
  from its oldest entry. Lessons are not news, so nothing is stale — the cost is re-hearing some.
  There is no server-side copy to restore, by design.
- Federal Register unreachable, or returning ZERO results: `data_availability.policy` goes false and
  the degraded ping lists "policy". Zero results across six agencies and 45 days is treated as a
  broken query rather than a quiet window — measured volume is ~21 documents — so it raises and is
  caught, deliberately, rather than shipping as an empty-but-healthy section. The Utah queue still
  drains on that run; a Utah-only failure never touches `data_availability.policy`.
- The Utah passed-bills page is unreachable, or its markup changed: the harvest is NOT stamped, so
  the gate stays open and tomorrow retries. Same when a scrape yields fewer than `UTAH_MIN_SIGNED`
  (100) signed bills — that is a half-loaded page or a changed row shape, not a real session, and
  stamping it would mark the session harvested for a year on one bad fetch. Early in a calendar year
  the harvest falls back to the previous year's session, so January cannot burn the gate on a session
  that has not happened yet.
- A single Utah bill's detail page fails: that stub is DROPPED from the queue rather than re-queued.
  This is deliberate — a permanently dead URL at the head of the queue would eat a fetch slot every
  day and block the whole backfill behind it — but it does mean the bill is gone until the next
  annual harvest. The log line names the id and the URL.
- The Utah bill JSON changes shape or goes away: text quality degrades, the leg does not fail. A Utah
  "detail page" is a JavaScript shell that paints itself from `/data/{session}/{number}.json` and
  carries NO bill text in the served HTML (its first ~1,800 stripped characters are site navigation),
  so `policy._fetch_bill_detail` reads that JSON first and keeps the legislature's own plain-language
  summary. When the JSON is unreachable, its session/number cannot be derived, or it carries under 80
  characters of provisions, the extractor falls back to the HTML page sliced to `<main>` — thin but
  honest — and PRINTS the bill id and the reason, because a Utah item summarized from that much text
  is a degraded item, not a normal one. Grep the job log for `falling back to the page`.
  `07-utah-bill-detail.py`'s A5 is the gate that makes a bad fallback loud: it asserts on the exact
  `summarize.POLICY_PROMPT_TEXT_CHARS` (500) slice that reaches the model, requiring bill language
  and NO navigation marker, with `UTAH_CHROME_CONTROL=true` as the proven negative control (it
  replays the pre-fix whole-page strip and must go red). Run 07 after any change to the extractor; if
  it ever passes under that control, A5 has stopped measuring anything. This bullet is a scar: the
  first version stripped the page whole, so the model got half a kilobyte of chrome and no bill text,
  and the invented-figure guard — which compares against that same string — then rejected every
  figure a Utah item carried. Nothing failed and nothing was logged, which is also what a healthy day
  looks like.
- Gemini fails during `summarize_policy()`: the section is empty for the day, the candidates are left
  UNSEEN, and tomorrow retries them. No crash push — a policy failure must never reach `main()`'s
  "briefing run crashed" handler. Federal candidates need no recovery — they are re-fetched from the
  45-day window every run. Utah stubs do, and they get it: `_release_utah()` popped them BEFORE the
  model ran and `state.save()` persists the shortened queue either way, so `_get_policy()` hands the
  candidates it actually sent back to `policy.requeue_utah()` on both the `ok=False` branch and its
  outer `except`. They go to the FRONT of `policy_utah_queue` in their original order, so the same
  bills are the next ones released tomorrow instead of landing behind a multi-month backfill, and the
  re-queue is id-deduped, so a double call cannot duplicate them (verified live: 3 stubs restored, no
  duplicates on a second call). **Do not clear `policy_utah_session` to "recover" these** — that
  triggers the full 491-row re-harvest for a loss that no longer happens.
  Two things are still dropped on purpose and are not bugs: a stub whose DETAIL FETCH failed never
  reaches the caller, so it is not re-queued (see the bullet above — a permanently dead URL at the
  head of the queue would eat one of the three daily slots forever), and a released stub that the
  abstract-level prefilter or the `MAX_POLICY_CANDIDATES` cap dropped was genuinely evaluated, so
  re-releasing it every day would block the backfill behind it.
- The policy section is empty on a normal day: that is the expected outcome, not a fault. Measured
  cadence is roughly one qualifying federal item per 22 days. The job log distinguishes the cases:
  `policy: 0 candidates, skipping model call` (no model spend at all — only when the PREFILTERED
  WINDOW is empty, which is now rare, since the seen set no longer trims the input), `sent N
  candidates, model selected M, K new after the already-reported drop`, `policy: dropped N
  already-reported selection(s): <ids>`, `policy: dropped N duplicate selection(s) in one response`,
  and a per-item `policy: dropped (<reason>)` line for every validator drop. "The model rejected
  everything", "the validator ate everything" and "everything it picked was old news" must never
  look alike.
- A same-date rebuild (`--force`, the normal manual path): the re-emit branch runs before any fetch,
  so the day's items are republished verbatim with no fetch, no model call and no second push. This
  is what stops a badly-timed re-run from overwriting `docs/archive/<date>.json` with an empty list
  and deleting items already delivered.
- The policy calendar has no failure mode to operate. It makes no request, holds no state and has no
  `data_availability` entry, so it cannot degrade and cannot appear in the degraded ping. The only
  ways it can be WRONG are editorial — a real-world date moved, or someone added an entry that names
  a year or claims a date nobody announced — and none of those is visible at runtime, because a
  rotted entry renders exactly like a good one. That is why the guard is a runnable gate
  (`09-policy-calendar.py`, in `run-all.sh` and in the weekly Data Smoke job) and not a log line.
  **After editing `config.POLICY_CALENDAR`, run 09** — it needs no key and no network:
  `PYTHONPATH=. BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/09-policy-calendar.py`.
  If a malformed entry ever does ship, production skips just that entry and prints
  `policy: calendar entry '<label>' skipped: ...` — the section degrades by one row, never by a run.
- **A transient HTTP failure on a policy or PMMS fetch** (the 2026-08-03 case: `federalregister.gov`
  returned 403 to the GitHub runner while the same call succeeded from home, after five dispatches in
  one afternoon; the next dispatch was green). `scripts/data/retry.py` now retries these in place —
  at most 3 attempts, 2s then 5s — for transient classes only: 403/408/425/429, any 5xx, timeouts,
  connection resets, truncated bodies. **400 and 404 are never retried** (a 400 is the misspelled-
  agency-slug signal the design relies on), and neither is any non-transport error. Every retry
  prints `retry: <what> — <reason> on attempt N/3 ...`, so **grep the job log for `retry:` to see a
  rate-limit episode**; previously the only symptom was the policy section rendering nothing behind
  a LOW-priority degraded ping. EXTRA attempts are capped per RUN at `RETRY_EXTRA_ATTEMPT_BUDGET`
  (4), bounding worst-case added wall time to 114s — under 20% of `briefing.yml`'s 600s cap — so a
  broad outage can never turn into a cancelled job, which would ship no briefing at all. When the
  budget is spent the log says so explicitly (`the per-run retry budget is spent, giving up to
  protect the job timeout`) and the pre-existing degrade path runs unchanged.
- Freddie Mac PMMS unreachable or unparseable: `get_rate()` returns None with a logged reason, the
  mortgage tile is omitted, and `data_availability.mortgage` goes false (so it appears in the
  degraded ping). It is deliberately NOT part of the `markets_ok` tuple: PMMS is a weekly Thursday
  release, and including it would fire the high-priority "market source may be down" page on any
  normal publishing gap. A rate several days old is healthy, not stale — the age check lives in the
  weekly assumption gate, not in production.
- GitHub Pages deploy fails with "Deployment failed, try again later": transient — re-run it
  (`gh run rerun <id>`).

## Regression tests

- Pre-flight and regression assumption tests live in `scripts/briefing-assumptions/` (see that
  directory's README for what each one proves and its negative controls).
- Run them all: `BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh`.
- Keyless and runnable anywhere: `04` (RSS + Wikipedia liveness), `05` (Federal Register, PMMS, the
  Utah list page), `07` (Utah bill detail: relative hrefs resolve, real text extracts, and **A6** —
  the passed-bills "Effective Date" column is still readable on >=95% of signed rows), `08` (keyword
  prefilter recall, precision and volume), `09` (the static policy calendar cannot go stale and no
  label claims an unannounced date), `10` (every Alphabet Soup seed article resolves; the
  invented-figure, dosage and length guards still bite; the tier list agrees across build, narration
  and client). `09` needs no network either, so it runs offline in milliseconds. `11` is JavaScript —
  it runs the shipped `docs/app.js` under Node against a stub DOM and is the ONLY gate on the lesson
  pointer, since no server-side check can see that rule regress:
  `BRIEFING_SMOKE_ALLOW_DEV=true node scripts/briefing-assumptions/11-client-pointer.js`.
  `06` needs a Gemini key; `03` needs a Gemini key; `01`/`02` need a Twelve Data key and target the
  abandoned v2 breadth route.
- `run-all.sh` halts on the first non-zero exit and `01`/`02` exit 3 without `TWELVEDATA_API_KEY`, so
  in practice gate on the policy tests individually or just dispatch **Data Smoke**, which runs
  05/07/08/09/10/11/06 from a runner with each step independent.
- **After editing `LESSON_SEED_ARTICLES`, run `10`.** Wikipedia titles move, and a title that no
  longer resolves is a silently missing lesson, not an error — the fallback simply produces nothing.
  `Credit utilization ratio` was in the shipped list for exactly as long as it took `10` to run once.

## Cost

- Zero per month. Yahoo Finance, RSS, the Federal Register API, the Utah Legislature pages, Freddie
  Mac's PMMS CSV, ntfy, GitHub Pages, and GitHub Actions (public repo) are all free and keyless.
  Gemini runs on the free tier; the Gemini project must keep billing disabled to stay free.
- The policy section adds at most one Gemini call per day, and since 2026-08-03 that call happens on
  MOST days rather than the ~3 a month the old pre-prompt dedupe produced: the model is now given the
  whole prefiltered window (~9-12 short documents) so that it is always ranking, and the call is
  skipped only when that window is empty. That is the accepted, deliberate cost of the ranking fix —
  one small call beside the two the briefing already makes, still inside the free tier.
  `data-smoke.yml` adds three more calls per week (one batch + two single-candidate measurements).
- Owen's Alphabet Soup adds two text calls a day (topic, then prose) and **three TTS calls**, taking
  the daily audio total from 1 to 4. Its source, Wikipedia's action API, is free and keyless. The
  real cost is disk: three clips per lesson at 48 kbps is roughly 1 MB a day of NEW blobs in a git
  history that is already permanent, which is why the outro is synthesized once and reused forever
  instead of daily. Note what `LESSON_AUDIO_RETAIN` does and does not buy: pruning reclaims
  WORKING-TREE bytes only, never history, so widening the window costs checkout size and nothing
  else — which is why it went from 10 to 21 once the reader's experience was weighed against it.
  Backfill adds at most `LESSON_AUDIO_BACKFILL_MAX` (2) TTS calls on a run that finds a gap, so the
  daily audio ceiling is 4 normally and 6 while a backlog drains.

## Local development

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=... NTFY_TOPIC=...      # PowerShell: $env:NAME="..."
python -m scripts.build_briefing --spine              # market/news/breadth/policy counts, no key needed
BRIEFING_STATE_PATH=/tmp/policy-state.json \
  python -m scripts.build_briefing --local --no-notify   # write docs/briefing.json, no push
```

**Use `BRIEFING_STATE_PATH` for every local run that is not deliberately editing real state.**
`state.save()` is called unconditionally at the end of `run()` — outside the `if do_notify:` block —
so `--local` and `--no-notify` still WRITE `state/state.json`. Without the override a dev run burns
`policy_bootstrapped`, marks the day's policy candidates seen, pops the Utah queue, and stamps the
day's lesson article into `lessons_taught` (so that article is never chosen again), all of which
silently suppress that content in the next real build; it can also stamp `last_run` and make the next
scheduled run no-op. Note the override does NOT cover `docs/lessons.json` or `docs/lessons/` — a
local run with a Gemini key writes a real deck entry and real clips there, so check `git status`
before committing. The override is the reason the mitigation is real rather than advice:
`config.STATE_PATH` used to be a plain constant with no environment hook.

It is read with `or`, not `os.environ.get(default)`, on purpose: an unset-but-present variable
arrives as the empty string, which a `get()` default would hand straight through as a path.
