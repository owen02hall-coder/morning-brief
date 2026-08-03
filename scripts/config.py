"""Central configuration for the morning briefing (v1 core).

Everything tunable lives here so the rest of the code reads as plain wiring. No secrets in this
file — keys come from environment variables (GEMINI_API_KEY, TWELVEDATA_API_KEY, NTFY_TOPIC).
"""
import os

# --- Timing -----------------------------------------------------------------
TIMEZONE = "America/Denver"          # user is in Utah (Mountain)
# The daily build de-dupes by DATE, not by hour (see build_briefing.main): the first cron to land
# each day builds, the rest no-op. GitHub delays scheduled jobs by hours, so an exact-hour gate
# would no-op every run — do not reintroduce one.

# --- AI (proven: gemini-2.5-flash + response_mime_type/response_schema) ------
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")
MODEL_FALLBACK = "gemini-2.5-flash-lite"   # model ids move; documented fallback

# --- News -------------------------------------------------------------------
NEWS_WINDOW_HOURS = 72               # widen past 24h so Mondays/holidays aren't empty
MAX_TECH_ITEMS = 3
MAX_WORLD_ITEMS = 3
MAX_CANDIDATES_PER_BUCKET = 25       # cap fed to the model to control token use

USER_AGENT = "morning-briefing/1.0 (personal use)"

WORLD_FEEDS = {
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "Guardian World": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
}
BUSINESS_FEEDS = {
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "CNBC": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
}
TECH_FEEDS = {
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "Hacker News": "https://hnrss.org/frontpage",
}

# --- Market data ------------------------------------------------------------
# All four headline numbers come from Yahoo Finance's keyless chart API (prior-close, day-over-day).
# Unlike most free tiers (incl. Twelve Data), Yahoo's chart endpoint includes indices, so it serves
# all four with no key. "Nasdaq" = the Nasdaq Composite (^IXIC); ^TNX is the 10-yr yield in percent.
# (FRED's keyless CSV was the prior source; it went unreachable from CI, so we moved to Yahoo.)
YAHOO_CHART = "https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
YAHOO_SYMBOLS = {"sp500": "^GSPC", "ndx": "^IXIC", "vix": "^VIX", "ten_year": "^TNX"}
MARKET_TIMEOUT = 20             # fail fast: a hung market source must not blow the 10-min job timeout.
                                # Yahoo answers in ~1s; worst case 4 symbols x 2 attempts x 2 hosts x
                                # 20s is bounded well under the cap. Markets degrade to None
                                # gracefully, so the AI summary still ships if the source is down.

# --- Market breadth (v2) -------------------------------------------------------
# "% of S&P 500 stocks above their 200-day MA", computed from a TradingView scanner POST (direct
# urllib — deliberately NOT the tradingview-screener library: that would drag pandas+lxml into the
# push-capable CI job for a one-endpoint JSON call) intersected with Wikipedia's constituent list.
# Unofficial endpoint: every call is wrapped, gated by BREADTH_MIN_MATCH, and cached last-good.
BREADTH_SCAN_URL = "https://scanner.tradingview.com/america/scan"
BREADTH_SCAN_LIMIT = 2000        # top-N US common stocks by market cap. 2000 + the type=stock
                                 # filter matches 500/503 constituents (validated 2026-07-05);
                                 # without the filter ~430 ADR/fund rows displace S&P names.
BREADTH_MIN_MATCH = 480          # of ~503 S&P constituents; fewer = shape drift -> fail closed
BREADTH_MIN_MATCH_NDX = 96       # of ~101 Nasdaq-100 constituents
SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Was https://en.wikipedia.org/wiki/Nasdaq-100 until 2026-07-13, when Wikipedia MOVED the component
# table off that article into its own list page. The old URL still resolves (200) but no longer
# contains id="constituents", so the parse raised "layout drift" and ndx100 breadth degraded to
# unavailable every day from 2026-07-13 to 2026-08-03 — 22 days, while the page itself looked fine.
# The list page keeps the same id="constituents" anchor and the same plain-text first cell, so only
# this URL changes (verified: 103 symbols, inside the 90-110 guard).
NDX100_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
BREADTH_WARN = 40                # one-shot warning when breadth FALLS below this...
BREADTH_WARN_CLEAR = 42          # ...re-armed only after recovering to here (no 39/41 flapping)
BREADTH_OVERSOLD = 30            # daily nag enters below this
BREADTH_CLEAR = 33               # nag clears at/above this (hysteresis; no 30/31 flapping)
BREADTH_EXTREME = 20             # flagged as extreme in the alert text
BREADTH_STALE_TRADING_DAYS = 2   # alerts suppressed when the value is older than this many trading days

# --- Policy that affects me ---------------------------------------------------
# A narrow, EFFECT-TESTED reversal of the "no US politics" rule in summarize.SYSTEM: an item ships
# only if it creates a NUMBER, a DEADLINE or an OBLIGATION for this one reader. Every value below is
# measured, not guessed — the evidence is scripts/briefing-assumptions/05..08 and their fingerprints.
# NOTE: no browser User-Agent lives here. PMMS and le.utah.gov need one, but it stays module-local in
# scripts/data/policy.py / mortgage.py, following market.py's YAHOO_UA precedent — a per-source quirk
# belongs next to the code that has the quirk, not in the shared surface.

# Injected into the policy prompt as the ONLY selection criterion (importance in general is
# explicitly not one). Proven wording: 06-policy-relevance.py:65-71 used exactly this paragraph to
# pick the 2 genuinely relevant documents out of 24 and to reject all 3 seeded decoys.
LIFE_PROFILE = (
    "24 years old, newly married, filing taxes jointly, living in Utah. Currently renting and "
    "actively saving to buy a first house. Has employer health insurance. No children yet. "
    "Cares about: mortgage rates and loan limits, down payments, property taxes, income tax "
    "brackets and deductions for married filers, health insurance costs, student loans, "
    "retirement contribution limits."
)

# Cheap keyword prefilter that runs BEFORE the model call, over title + abstract. Stored lowercase;
# matched with a word boundary plus an inflection group (see policy._kw_pattern), which is why BOTH
# forms are listed wherever suffixing fails: "house" + "ing" = "houseing" and "property" + "es" =
# "propertyes" are not words, so "housing" and "properties" are spelled out instead of trusted to a
# regex group. Keywords ending in a non-word char ("401(k)") get no trailing boundary — one can
# never match there.
# PROVEN (08-prefilter-recall.py, 2026-08-03): this exact list retains both Federal Register
# documents the live model selected, retains 4/4 known-relevant Utah titles on TITLE ALONE (all the
# harvest has before the detail fetch), admits 0/4 decoys, and admits only 3.5% of the 491 signed
# 2026GS Utah bills against an 18% ceiling. 08 imports this constant, so editing the list here moves
# the gate with it — a broadened list that turns selection into a lottery goes red in CI.
LIFE_PROFILE_KEYWORDS = [
    "mortgage", "loan limit", "down payment", "closing cost", "escrow", "appraisal",
    "house", "housing", "home", "homebuyer", "first-time buyer", "rent", "rental", "landlord",
    "property tax", "properties", "zoning", "adu",
    "income tax", "tax bracket", "standard deduction", "deduction", "married filing jointly",
    "withholding", "tax credit",
    "student loan", "repayment", "borrower", "pell", "direct loan",
    "health insurance", "health plan", "premium", "open enrollment", "hsa", "marketplace",
    "retirement", "401(k)", "ira", "contribution limit",
]

# Federal Register — one keyless request covers all six agencies, type-filtered and date-windowed.
# It is the backbone rather than a collection of per-agency feeds because CFPB / FHFA / IRS / HUD
# rulemaking all land here anyway, and their own feeds are dead or key-gated (05's KNOWN-DEAD list).
FR_API = "https://www.federalregister.gov/api/v1/documents.json"
# Deliberately `employee-benefits-security-administration` and NOT the whole `labor-department`:
# measured 2026-08-03, the parent slug returned 46 documents in 45 days of which 26 were Labor —
# almost entirely OSHA chemical-exposure limits (benzene, asbestos, cadmium, ethylene oxide) and Mine
# Safety rules, none of which can touch this reader. Narrowing to EBSA (health plans + retirement,
# the only in-scope Labor sub-agency) cut the candidate set 46 -> 21 with ZERO loss of relevant
# items. Filtering noise at the source beats spending model tokens rejecting it.
# A misspelled slug returns HTTP 400, not an empty set (05:27-31) — a typo here fails loudly.
FR_AGENCIES = [
    "housing-and-urban-development-department",
    "federal-housing-finance-agency",
    "consumer-financial-protection-bureau",
    "internal-revenue-service",
    "employee-benefits-security-administration",
    "education-department",
]
# Exactly the fields the item format needs. `effective_on` is legitimately null on proposed rules —
# every date comparison and sort key downstream must be None-safe or the policy leg raises into
# build_briefing.main()'s crash handler and pages the whole briefing as FAILED.
FR_FIELDS = ["title", "html_url", "publication_date", "type", "agencies",
             "abstract", "effective_on", "document_number"]
FR_WINDOW_DAYS = 45      # measured cadence is ~1 qualifying item per 22 days (2 of 24 across 45
                         # days), so a 24h window would be empty almost every morning. Dedupe is by
                         # document_number against state.policy_seen — applied to what the model
                         # SELECTED, not to what it is shown — so a wide window re-reports nothing;
                         # it only means a missed run or a dead day loses nothing.
FR_PER_PAGE = 100        # the API's page cap. Measured volume is 21 documents / 45 days
                         # (05-policy-sources.fingerprint.json), so one page covers it ~5x over.
                         # If volume ever passes this the API truncates SILENTLY; the guard is 05's
                         # FR_MAX_EXPECTED, which only works because `count` reports total matches
                         # independent of page size (asserted in 05 via FR_PER_PAGE_OVERRIDE).

# Utah Legislature — the higher-signal half, and HTML scraping is the only route: Utah publishes no
# JSON API, its bulk "Bill Data" link is an iframe wrapper, and the Tax Commission feed is
# published-but-dead (all probed 2026-08-03; see 05's KNOWN-DEAD block).
UTAH_BASE_URL = "https://le.utah.gov"           # row hrefs are RELATIVE (/~2026/bills/static/...);
                                                # urljoin against this or the host allowlist drops
                                                # 100% of Utah items while every gate stays green
                                                # (proven in 07-utah-bill-detail.py, A1).
UTAH_PASSED_URL = UTAH_BASE_URL + "/asp/passedbills/passedbills.asp?session={session}"
UTAH_MIN_SIGNED = 100    # harvest gate: only trust a scrape that yields at least this many
                         # governor-signed bills. The 2026 general session yielded 491 signed of 495
                         # rows, and a session that has not happened yet yields ~0 — so 100 sits far
                         # below a real session and far above a broken parse or a half-loaded page.
                         # Without it, one bad fetch would mark the session harvested for a year.

# Freddie Mac PMMS — the 30-year mortgage rate. The only part of this feature with content 52 weeks
# a year, and the single most decision-relevant number for someone saving for a first house.
# Weekly release; 2,889 rows, newest 2026-07-30 at 6.66 (05 fingerprint). Needs a browser-like UA.
PMMS_CSV_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"

POLICY_TIMEOUT = 25              # per request. Matches what 05/07 proved; Utah detail pages answered
                                 # well under 20s each. The whole policy leg must stay inside
                                 # briefing.yml's timeout-minutes: 10 — a cancelled job ships no
                                 # briefing at all and fires a high-priority FAILED push.
MAX_POLICY_ITEMS = 3             # rendered per day; also the cap on Utah DETAIL fetches per run,
                                 # which is what keeps the annual Utah backfill (491 bills) from
                                 # fanning out into hundreds of requests inside that 10-minute budget.
MAX_POLICY_SELECTIONS = 6        # asked of the MODEL, and deliberately larger than MAX_POLICY_ITEMS.
                                 # The seen-set dedupe now runs AFTER selection (see
                                 # build_briefing._new_policy_items), so a ranked list that is only
                                 # MAX_POLICY_ITEMS long can be consumed entirely by already-reported
                                 # documents and ship nothing. The extra headroom is what lets a NEW
                                 # item survive that drop; the rendered cap is still MAX_POLICY_ITEMS.
MAX_POLICY_CANDIDATES = 25       # sent to the model (mirrors MAX_CANDIDATES_PER_BUCKET above)
MAX_POLICY_UPCOMING = 5          # "What's coming": already-reported items with a future
                                 # effective_date, carried until that date passes.

# --- Audio edition (TTS) ------------------------------------------------------
# One TTS request/day stays comfortably inside the Gemini free tier. The build writes a WAV to
# AUDIO_WAV_PATH (job-local, gitignored); the workflow converts it to docs/briefing-audio.mp3 and
# writes docs/briefing-audio.json so the client can verify the audio matches today's edition.
TTS_MODEL = os.environ.get("TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "Kore")   # warm, clear prebuilt voice

# --- Notifications / hosting ------------------------------------------------
# Public Pages URL of the PWA; set as an env var/secret at deploy time.
# `or` (not a get() default): an UNSET repo variable reaches CI as the empty string, which get()
# would return as-is — silently bypassing the placeholder warning and shipping an empty click-URL.
PAGES_URL = os.environ.get("PAGES_URL") or "https://example.github.io/morning-briefing/"
NTFY_BASE = "https://ntfy.sh"

# --- Paths ------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")
BRIEFING_PATH = os.path.join(DOCS_DIR, "briefing.json")
# `or` (not a get() default), same reason as PAGES_URL: an unset-but-present env var arrives as "".
# The override exists because state.save() runs UNCONDITIONALLY at the end of run() — outside
# `if do_notify:` (build_briefing.py:228-231) — so a `--local` dev run writes REAL state: it burns
# policy_bootstrapped and marks the day's policy candidates seen, which silently suppresses them in
# the next real build. Point BRIEFING_STATE_PATH at a throwaway file to run --local safely.
STATE_PATH = os.environ.get("BRIEFING_STATE_PATH") or os.path.join(REPO_ROOT, "state", "state.json")
# Handoff file: the build writes today's headline here; the workflow's post-publish step reads it
# to send the "ready" push ONLY after git push succeeds (never committed — see .gitignore).
HEADLINE_PATH = os.path.join(REPO_ROOT, "headline.txt")
# Audio handoff: ready-to-publish mp3 encoded in-process (lameenc — the runner has no ffmpeg);
# the workflow moves it into docs/ (never committed from here — see .gitignore).
AUDIO_MP3_PATH = os.path.join(REPO_ROOT, "audio.mp3")

# --- Monitoring -------------------------------------------------------------
# The client-side staleness threshold (PWA "couldn't refresh" banner, 28h) lives in docs/app.js
# (STALE_HOURS) — the PWA can't read this file, so a knob here would be a dead duplicate.
MARKETS_STALE_DAYS = 2               # build pages HIGH-priority if all four market numbers have been
                                     # unavailable this many days running (a dead source, not a 1-day
                                     # blip). A single bad day stays a low-priority "degraded" ping.
HEARTBEAT_STALE_HOURS = 30           # server: heartbeat.yml pages if the LIVE page is older than this.
                                     # > 24h + GitHub's worst observed schedule jitter (~9h, on the
                                     # build AND on the heartbeat itself) so a healthy-but-jittery day
                                     # never false-alarms; a real multi-day freeze trips it well within
                                     # a day of going stale. It is a freeze backstop, not a punctuality
                                     # check — do not tighten it toward 24h.
