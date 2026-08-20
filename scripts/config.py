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
MAX_WORLD_ITEMS = 4      # 3 -> 4 on 2026-08-20. The reader asked for "more of it" and a review of a
                         # week of archives showed this bucket was already delivering the
                         # things-to-be-aware-of he wanted; widening it beat adding a second,
                         # duplicate world section.
MAX_US_ITEMS = 3         # US national news. See US_FEEDS below for why this section exists at all.
MAX_SCIENCE_ITEMS = 2    # Health and science. Deliberately the smallest news section: it is the
                         # fourth added to a drive-time cut, and its value is awareness rather than
                         # coverage — two things worth knowing beats five worth skimming.
MAX_CANDIDATES_PER_BUCKET = 25       # cap fed to the model to control token use

USER_AGENT = "morning-briefing/1.0 (personal use)"

WORLD_FEEDS = {
    "BBC World": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "Guardian World": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1004/rss.xml",
}
# US national news. This section RE-ADMITS a category summarize.SYSTEM deliberately excluded
# ("World news: only globally significant events, not granular or partisan US politics"). That
# exclusion was the cheapest way to keep partisan shouting out, and it worked — but it also meant a
# Supreme Court ruling, a hurricane landfall, a recall or a major federal action reached this reader
# NOWHERE: the policy section only carries rules that affect him personally, and world only carries
# the globally significant.
#
# Re-admitting the category safely needs a rule, not good intentions, so summarize.SYSTEM now
# carries the events-not-contest rule and 13-us-news-editorial.py enforces it.
#
# The two feeds were chosen on PROBED CONTENT SHAPE, not availability — all four candidates were
# alive on 2026-08-20; what separated them was what they emit. AP led with "Alfalfa sprouts linked to
# food poisoning illnesses" and NPR National with "What we know about the Penn State cocaine
# trafficking..." — both events. Guardian US led with "Melania Trump appears to nod to questions
# about absence", which is precisely the political gossip the original exclusion existed to block,
# so it is REJECTED rather than merely unused. CBS US is held in reserve: alive and event-based, but
# heavily crime-weighted, and a briefing of daily crime is its own failure mode.
US_FEEDS = {
    "AP": "https://feedx.net/rss/ap.xml",
    "NPR National": "https://feeds.npr.org/1003/rss.xml",
}
# Health and science. Named "disasters" in the 2026-08-20 brief and deliberately NOT built that way:
# a disaster already reaches this reader through the sections that exist (Indonesia's earthquake came
# through world, Indiana's nine-day outage through US), so a third home for it would have produced a
# section that mostly re-tells the other two. `tts._dedupe_across` would then quietly suppress it,
# which is a section whose main behaviour is disappearing.
#
# Sources chosen on probed content shape, 2026-08-20, and this category punished the obvious picks
# hardest. BBC Health is the standout — "Vaccine breakthrough stops cancer returning in trial",
# "Weekly type 2 diabetes jab could replace daily injections", "Vapes could lead to health harms in
# children" — findings a person can act on. REJECTED: BBC Science & Environment (UK-domestic: UK
# flood warnings, a UK glass-deposit scheme), Guardian Environment (US environmental POLITICS, which
# the US NEWS RULE exists to keep out), NASA (press releases), ScienceDaily (journal churn, e.g.
# "Schizophrenia's lost brain connections follow a surprising..."). CIDRAP's outbreak feed 404s.
#
# NPR's two desks carry real signal (a record cyclosporiasis outbreak, the fastest known star) mixed
# with science POLITICS (an FDA nomination, a logging decision). The prompt rule for this section
# asks for findings over politics; the same discipline as US_FEEDS, applied to a different failure.
SCIENCE_FEEDS = {
    "BBC Health": "https://feeds.bbci.co.uk/news/health/rss.xml",
    "NPR Science": "https://feeds.npr.org/1007/rss.xml",
    "NPR Health": "https://feeds.npr.org/1128/rss.xml",
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
    # Added 2026-08-03 after CI run 30857451845: the model selected HUD's "Rescission of Floodplain
    # Management ... Minimum Property Standards for Flood Hazard Exposure" and 06's G2/prefilter
    # assertion caught that this list filtered it OUT — so in production that document would never
    # have reached the model and the section would just have looked quiet. Flood-risk building
    # standards govern what an FHA-insured home must meet and whether flood insurance is required,
    # which is squarely a first-time buyer's problem. "floodplain" is listed separately because
    # \bflood\b cannot match it (the 'p' is a word character, so there is no boundary after 'flood').
    "flood", "floodplain", "property standard",
    "income tax", "tax bracket", "standard deduction", "deduction", "married filing jointly",
    "withholding", "tax credit",
    "student loan", "repayment", "borrower", "pell", "direct loan",
    "health insurance", "health plan", "premium", "open enrollment", "hsa", "marketplace",
    "retirement", "401(k)", "ira", "contribution limit",
    # Added 2026-08-20 after the model selected IRS 2026-16314 ("Employer Contributions to Trump
    # Accounts and Nondiscrimination Rules for Dependent Care Assistance Programs") and 06's
    # G2/prefilter caught that this list filtered it OUT. A real recall gap, and the same shape as
    # the "floodplain" addition above: the profile already covers HSA, health plans and open
    # enrollment, and a dependent care FSA is the same category of employer benefit — pre-tax money
    # (~$5k/yr) that changes take-home pay, with nondiscrimination testing that can force a refund
    # mid-year. Distinguish this from LIFE_PROFILE_EXCLUSIONS' pension entry: that document's
    # "affects participants" was Federal Register boilerplate over employer-side actuarial
    # machinery, whereas DCAP rules govern what an EMPLOYEE may actually set aside and keep.
    # "Trump account" rides along because the same rulemaking stream carries both and it is a
    # tax-advantaged account a family can hold.
    "dependent care", "dependent care assistance", "childcare", "child care", "daycare",
    "flexible spending", "fsa", "trump account",
]

# Topics the profile deliberately does NOT cover, with the reason. This is the companion to the list
# above and exists to answer a question that list cannot: when the model picks a document the
# prefilter rejected, is that a RECALL GAP (the prefilter is too narrow — add a keyword, as
# "floodplain" was added on 2026-08-03) or a deliberate scope decision the prefilter got RIGHT?
#
# Without this, 06-policy-relevance.py's G2 has to read every such disagreement as a recall gap, so
# the only way to make the gate green is to widen the prefilter — which is backwards when the honest
# answer is "this genuinely does not affect me". A red gate that can only be silenced by importing
# noise stops being a signal, and the pressure is to delete the check.
#
# Each entry must carry its reason, and this list must stay SHORT. It is not a mute button: an entry
# here is a standing claim that a whole topic is out of scope, and 06 prints every skip it causes so
# the claims stay visible on every run. If a topic here ever starts mattering, delete the entry and
# add the keyword instead.
LIFE_PROFILE_EXCLUSIONS = [
    # 2026-08-20. The IRS/Treasury stream of single-employer DEFINED BENEFIT funding rules (target
    # normal cost, funding target, segment rates, mortality tables) governs how an EMPLOYER must
    # fund a pension plan, not what a participant receives, and this reader's retirement exposure is
    # defined-CONTRIBUTION — which is why the keyword list carries 401(k)/IRA/contribution limit and
    # no pension vocabulary. Federal Register abstracts on these routinely say they "affect
    # participants in, beneficiaries of, employers maintaining, and administrators of" such plans,
    # which is boilerplate broad enough to make the model select them; that is exactly the
    # over-selection this entry records as intentional rather than as a prefilter bug.
    ("pension funding / defined benefit plan mechanics",
     ["defined benefit", "target normal cost", "funding target", "minimum funding",
      "single-employer plan", "pension plan"]),
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

# --- Bounded retry for the policy + mortgage HTTP legs (scripts/data/retry.py) -------------------
# WHY: on 2026-08-03, CI run 30859893450, federalregister.gov answered the GitHub runner with HTTP
# 403 while the identical request succeeded from a home connection; the very next dispatch
# (30859980835) was green. Transient rate limiting — we hit that API across five dispatches in one
# afternoon. One 403 makes policy._federal_candidates() raise, so available=False, the section
# renders nothing, and the only signal is a LOW-priority degraded ping. Silent AND recurring is
# exactly the two-part gate this project uses to decide a failure earns a machine.
# The retry classifier itself lives in scripts/data/retry.py; only the budget numbers are here.
RETRY_MAX_ATTEMPTS = 3           # 1 initial + at most 2 retries
RETRY_BACKOFF_SECONDS = (2, 5)   # before retry 1, before retry 2. Small on purpose: this shares
                                 # briefing.yml's 10-minute budget with everything else, and a
                                 # rate-limit window that needs more than 7s of patience is not one
                                 # a morning build should sit through.
RETRY_EXTRA_ATTEMPT_BUDGET = 4   # EXTRA attempts allowed across the WHOLE run (see retry.py). Not a
                                 # per-call number: the retried surface is up to 12 requests (PMMS,
                                 # Federal Register, <=2 Utah list pages, <=2 backfill list pages,
                                 # <=3 bill JSON + <=3 HTML fallbacks), and an unbudgeted
                                 # 3-attempts-each would put ~900s of
                                 # worst case inside a 600s job. Worst case ADDED here is
                                 # 4 x POLICY_TIMEOUT + 14s of backoff = 114s (~1.9 min, under 20%
                                 # of the job cap), and it is only reachable if four separate
                                 # requests each hang for the full 25s — a total outage in which the
                                 # section is lost regardless. 4 with a 2-retry-per-call ceiling also
                                 # means the FIRST retried call can never starve the second: PMMS
                                 # (which runs first) can consume at most 2, leaving >=2 for the
                                 # federal leg this exists for.
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

# --- The weekly spoken policy digest -------------------------------------------------------------
# The audio reads the policy section ONCE A WEEK (Monday), not daily. A once-a-week readout can only
# be honest if it covers the whole week, and `briefing.json` holds only TODAY's finds — so
# state.record_policy keeps a rolling record of what was reported on each of the last
# POLICY_WEEK_DAYS days and the narration reads that. Without it, an item found on Wednesday would
# never be spoken at all: Monday's briefing does not contain it, and Wednesday's audio skipped the
# section. That is a SILENT loss of the exact thing the reader asked to hear.
POLICY_WEEK_DAYS = 7             # rolling window of reported policy items kept for the digest.
POLICY_AUDIO_WEEKDAY = 0         # Monday (date.weekday(): Mon=0 .. Sun=6). The weekly recap rides
                                 # Sunday; the policy digest is deliberately its own day so neither
                                 # segment is buried behind the other in a single long edition.
MAX_POLICY_SPOKEN = 6            # hard cap on items read aloud in the digest, newest first. The
                                 # window is bounded by days, not by count, and a heavy federal week
                                 # could otherwise turn the drive-time cut into a ten-minute recital.

# --- The policy calendar: the recurring dates that have NO feed to watch ------------------------
# The annual dollar figures this reader most wants — the conforming loan limit, the IRS brackets and
# married-filing-jointly standard deduction, the 401(k)/IRA limits, the ACA enrollment window — are
# NOT in the Federal Register at any document type, and none of them has a machine-readable feed.
# Measured 2026-08-03 (integrations.md, "Adding conditions[type][]=NOTICE"): adding NOTICE to the FR
# query multiplies candidate volume 5.4x and still returns none of them; full-text search across ALL
# document types over 400 days finds 0 hits for the IRS phrases and 1 irrelevant hit for "conforming
# loan limit"; the FHFA/IRS/HUD RSS feeds are 404 at every documented-looking path.
#
# So the shipped section can only ever REACT to rulemaking. A small hardcoded calendar is the correct
# mechanism for the rest precisely BECAUSE those announcements have no feed — there is nothing to
# scrape, and this is the only way the briefing can say "the loan limit lands in the next few weeks".
#
# THREE PROPERTIES MAKE THIS SAFE TO HARDCODE, and 09-policy-calendar.py is the machine that keeps
# them true (a comment is not a mechanism):
#
# 1. NO ENTRY CARRIES A YEAR. Every entry is a month/day RULE, resolved forward against the run's
#    date by policy._next_occurrence(). An entry therefore cannot go stale: it rolls into next year
#    the day after it passes. A `year` key here is a bug, and C2 goes red on one.
#
# 2. EVERY LABEL IS ANTICIPATORY, NEVER A FACT. Exact dates move year to year, so a label says
#    "expected late November", never "November 25". This is the same principle as the model never
#    authoring a figure: we do not state a date the source has not announced. C5 enforces it — every
#    label must contain the word "expected" and must contain no 4-digit year and no "Month DD".
#    Precise dates and their sourcing live in `note`, which is explanatory context, not a claim
#    about this year.
#
# 3. THE MONTH/DAY IS THE **END** OF THE PLAUSIBLE WINDOW, not a guess at the date. Anchoring on the
#    late edge means the entry is visible for the whole period during which the event could land and
#    never rolls forward while the event is still ahead — the failure that would make the calendar
#    worse than nothing. It also means the anchor is never a claim: it is "by when", not "on".
#
# Each url was fetched 2026-08-03 and returned HTTP 200 (some via redirect). They are for a human to
# click; nothing here is fetched at runtime, and the calendar has NO failure surface at all.
POLICY_CALENDAR = [
    {
        "month": 11, "day": 30,
        "label": "FHFA conforming loan limit for next year — expected late November",
        "note": ("The cap on a conforming (non-jumbo) mortgage, and the line between a normal rate "
                 "and a jumbo one. FHFA has announced it in the last days of November each year, "
                 "and the new limit applies to loans made from January 1."),
        "url": "https://www.fhfa.gov/data/conforming-loan-limit",
    },
    {
        "month": 11, "day": 10,
        "label": ("IRS tax brackets and the married-filing-jointly standard deduction for next "
                  "year — expected late October or early November"),
        "note": ("Published as an annual inflation-adjustment revenue procedure; recent releases "
                 "landed between mid-October and mid-November. These are the bracket thresholds "
                 "and the standard deduction the next return is filed against."),
        "url": "https://www.irs.gov/filing/federal-income-tax-rates-and-brackets",
    },
    {
        "month": 11, "day": 5,
        "label": ("IRS 401(k) and IRA contribution limits for next year — expected late October "
                  "or early November"),
        "note": ("The annual cost-of-living adjustment notice, historically released within a week "
                 "or two of the bracket figures. It sets how much can go into a 401(k) and an IRA "
                 "next year."),
        "url": ("https://www.irs.gov/retirement-plans/"
                "cola-increases-for-dollar-limitations-on-benefits-and-contributions"),
    },
    {
        "month": 11, "day": 1,
        "label": "ACA marketplace open enrollment opens — expected early November",
        "note": ("healthcare.gov has opened enrollment on November 1 each year, and currently "
                 "publishes December 15 as the deadline for coverage starting January 1. The "
                 "window is set by federal rule and has been changed by rulemaking before."),
        "url": "https://www.healthcare.gov/quick-guide/dates-and-deadlines/",
    },
    {
        "month": 1, "day": 15,
        "label": "ACA marketplace open enrollment closes — expected mid-January",
        "note": ("healthcare.gov currently publishes January 15 as the last day to enroll in or "
                 "change a marketplace plan. After it closes, enrolling needs a qualifying life "
                 "event. The closing date is rule-set and has moved before — confirm the year's "
                 "actual date on healthcare.gov."),
        "url": "https://www.healthcare.gov/quick-guide/dates-and-deadlines/",
    },
    {
        "month": 4, "day": 18,
        "label": "Federal income tax filing deadline — expected mid-April",
        "note": ("April 15 by statute, moving to the next business day when that falls on a "
                 "weekend or a District of Columbia holiday, which has pushed it to April 17 or "
                 "18 in several recent years."),
        "url": "https://www.irs.gov/filing/individuals/when-to-file",
    },
    {
        "month": 1, "day": 21,
        "label": "Utah Legislature's general session convenes — expected mid-to-late January",
        "note": ("The general session opens on the third Tuesday in January (so January 15-21 "
                 "depending on the year) and runs 45 calendar days, adjourning in early March. "
                 "Bills the governor signs reach this section from the passed-bills list "
                 "afterwards, which is why the Utah half is dark most of the year."),
        "url": "https://le.utah.gov/session/",
    },
    {
        "month": 8, "day": 31,
        "label": "Utah Truth in Taxation hearings — expected during August",
        "note": ("A Utah taxing entity that wants more property tax revenue than the certified "
                 "rate allows must hold a public hearing, and those hearings are held in August. "
                 "The county's Notice of Property Valuation and Tax Changes, mailed in July, "
                 "carries the actual date and place for a given parcel."),
        "url": "https://propertytax.utah.gov/",
    },
]
POLICY_CALENDAR_HORIZON_DAYS = 30
# Why 30 and not 60 or 7. Eight events a year, each anchored at the end of its window, produce these
# visible spans: Oct 2-Nov 30, Dec 16-Jan 21, Mar 19-Apr 18, Aug 1-31 — 159 days, so the
# forward-looking block appears on roughly 44% of mornings. That is the point of the number: useful
# without making the section always-on. "Policy that affects you" renders ONLY when it is non-empty
# (an empty section is a correct outcome, not a fault — architecture.md), and a horizon wide enough
# to keep a calendar entry on screen every day would silently undo that decision by making the
# section permanent. A 7-day horizon would swing the other way and give no planning lead at all.

# --- Owen's Alphabet Soup: one grounded, useful-for-life lesson a day --------------------------
# The last section of the page and the last thing in the audio edition. Everything else in this
# briefing REACTS to a feed; this is the only section whose job is to teach something that is true
# whether or not it happened today.
#
# THE ACCURACY MECHANISM IS THE SAME ONE THE POLICY SECTION USES, and it is the whole reason this
# section is safe to ship: the model NEVER writes from memory. A real article is fetched first
# (scripts/data/lessons.py), its text is handed to the model as untrusted source material, and the
# prose that comes back is checked IN CODE against that text — an invented dollar figure, percentage
# or year discards the lesson (summarize._validate_lesson). The citation is re-taken from the fetch,
# never echoed from the model. "The model was told to be accurate" is a label; this is a mechanism.
#
# THE POINTER IS NOT HERE. The build publishes an append-only DECK (docs/lessons.json); which lesson
# is "current" is decided on the phone, because only the phone can know whether the audio actually
# reached the end. See docs/app.js (the `soup` object) and documentation/architecture.md.

# Even rotation, picked by (number of lessons already taught) % len(LESSON_DOMAINS) — deterministic,
# survives skipped days, and cannot cluster five money lessons in a row. Each `focus` line is the
# only steering the topic-proposal call gets.
LESSON_DOMAINS = [
    {"name": "Money mechanics",
     "focus": ("How money machinery actually works under the hood: credit, escrow, interest, "
               "insurance, taxes, retirement accounts, closing costs, loan structure.")},
    {"name": "Home, car and repair",
     "focus": ("Owning and maintaining physical things: plumbing, electrical, heating, appliances, "
               "tires, engines, tools, inspections, and the failures that get expensive when "
               "ignored.")},
    {"name": "Health and emergencies",
     "focus": ("What to recognise and what to do when something goes wrong with a body: first aid, "
               "warning signs, prevention, sleep, and when professional care is the answer.")},
    {"name": "Thinking and people",
     "focus": ("How judgement goes wrong and how people are persuaded: decision traps, statistics "
               "literacy, negotiation, communication, scams and manipulation tactics.")},
]

# Fallback article titles, used ONLY when the proposal call fails or none of its candidates resolve
# to a real, long-enough article. Deliberately concrete English Wikipedia titles, not search terms:
# a title either fetches or it does not, which fails loudly instead of quietly returning something
# adjacent. Same reasoning as POLICY_CALENDAR above — where there is no feed, a curated static list
# is the honest mechanism, and it is a FLOOR under the model, not a replacement for it.
LESSON_SEED_ARTICLES = {
    "Money mechanics": [
        "Credit score", "Escrow", "Amortization schedule", "Compound interest", "Index fund",
        "Deductible", "Health savings account", "Annual percentage rate", "Title insurance",
        "Individual retirement account", "Property tax", "Debt-to-income ratio", "Closing costs",
    ],
    "Home, car and repair": [
        "Circuit breaker", "Water heater", "Residual-current device", "Smoke detector",
        "Carbon monoxide poisoning", "Home inspection", "Motor oil", "Tire", "Water hammer",
        "Antifreeze", "Jump start (vehicle)", "Air filter",
    ],
    "Health and emergencies": [
        "Cardiopulmonary resuscitation", "Abdominal thrusts", "Burn", "Stroke", "Anaphylaxis",
        "Hypothermia", "Heat stroke", "First aid", "Automated external defibrillator",
        "Sleep hygiene", "Dehydration", "Concussion",
    ],
    "Thinking and people": [
        "Confirmation bias", "Sunk cost", "Base rate fallacy", "Survivorship bias",
        "Anchoring effect", "Availability heuristic", "Loss aversion", "Active listening",
        "Negotiation", "Social engineering (security)", "Confidence trick", "Framing effect",
    ],
}

# English Wikipedia's action API — keyless, no account, generous rate limits for one request a day.
# `formatversion=2` gives a plain `pages` LIST (the legacy shape is a dict keyed by page id, with
# "-1" for a miss, which is exactly the kind of shape a caller silently mis-reads).
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_TIMEOUT = 20
LESSON_MIN_SOURCE_CHARS = 900     # below this an article is a stub — not enough to teach from, and
                                  # the model would have to fill the gap from memory, which is the
                                  # one thing this design exists to prevent.
LESSON_SOURCE_CHARS = 7000        # slice of the article handed to the model. The figure guard reads
                                  # the FULL extract, so (as in _policy_docs_block) truncation can
                                  # only ever shrink what the model can copy — never cause a false drop.
LESSON_TOPIC_CANDIDATES = 4       # asked of the proposal call, tried in order until one fetches.
                                  # One call, several shots: a retry costs a request, this does not.

# Length tiers. The reader picks one on the phone (localStorage), so the build must publish ALL
# THREE — hence three prose fields per lesson and three audio segments, played cumulatively:
# quick = [1], medium = [1,2], long = [1,2,3]. Segments (not three separate renderings) is what
# keeps this to one lesson's worth of audio instead of three.
LESSON_WORD_TARGETS = {"quick": (110, 170), "more": (110, 180), "deep": (130, 220)}
LESSON_WORD_FLOOR = 55            # below this a segment is not a lesson; the whole item is rejected
LESSON_WORD_CEILING = 320         # above this the audio blows past the tier the reader chose

LESSON_DECK_MAX = 60              # entries kept in docs/lessons.json. The phone's pointer walks this
                                  # list; anything older has been read or skipped many times over.
LESSON_AUDIO_RETAIN = 21          # lessons whose mp3s stay in docs/lessons/ (~900 KB each, three
                                  # clips at ~300 KB). Raised from 10 on 2026-08-20. The old value
                                  # was justified by "every daily commit is permanent git history",
                                  # which is true of CREATING a clip and NOT of keeping it: the blob
                                  # is in history from the commit that added it, so pruning reclaims
                                  # working-tree/checkout bytes only and never shrinks the repo.
                                  # The window therefore trades ~19 MB of checkout — not of history
                                  # — against the reader's actual experience, and 10 was losing
                                  # that trade badly: the pointer serves the OLDEST unfinished
                                  # lesson, so a reader two weeks behind met the phone's own voice
                                  # on every lesson they were behind by. 21 covers three weeks.
                                  # A pointer that still falls off the window works — the client
                                  # reads that lesson with the on-device voice.
LESSON_BOOTSTRAP_COUNT = 2        # first run only: seed a small buffer so the "new lesson" button
                                  # has somewhere to go on day one. 1/day after that.
LESSON_TTS_MIN_INTERVAL = 20      # seconds between TTS requests. The free tier is rate-limited per
                                  # MINUTE, and this feature takes the daily count from 1 to 4.
LESSON_AUDIO_DEADLINE = 420       # seconds INTO run() past which no more lesson clips are
                                  # synthesized. Measured from the start of the run, not from the
                                  # start of the audio leg, because the thing being protected is
                                  # briefing.yml's `timeout-minutes: 10` — a cancelled job ships NO
                                  # briefing at all and fires the high-priority FAILED push, which
                                  # is strictly worse than a lesson the phone has to read aloud
                                  # itself. 420 leaves ~2.5 min of margin for the commit/push/notify
                                  # legs that still have to run after this.

LESSON_AUDIO_BACKFILL_MAX = 2     # missing clips repaired per run, for lessons STILL INSIDE the
                                  # LESSON_AUDIO_RETAIN window. A tier lost to a transient TTS error
                                  # used to be lost forever: generate_lesson_audio only ever ran for
                                  # the entries created that day, so nothing revisited an older one.
                                  # The reader then met the phone's own voice on that lesson — the
                                  # deck's oldest unfinished entry is the one the pointer serves
                                  # first, so a single bad morning could sit at the head of the queue
                                  # for weeks. Bounded per run so the repair can never crowd out
                                  # today's own clips or the free tier's daily budget.
TTS_RETRY_ATTEMPTS = 2            # extra attempts per TTS request (so 3 tries total) on a TRANSIENT
                                  # failure. The free tier answers 429/503 often enough that a
                                  # single-shot request loses tiers in normal operation; that is how
                                  # 2026-08-13 shipped with no `quick` clip and 2026-08-14 with no
                                  # `more`. Retrying is what stops the backfill above from being a
                                  # permanent cleanup crew for a leak upstream of it.
TTS_RETRY_BACKOFF = 8             # seconds, multiplied by the attempt number. Deliberately larger
                                  # than the data-fetch backoff: TTS rate limits are per MINUTE, so
                                  # a fast retry is guaranteed to hit the same wall.

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
# Owen's Alphabet Soup. The deck is PUBLISHED (the PWA fetches it like briefing.json) and is
# append-only + pruned; the audio for the most recent LESSON_AUDIO_RETAIN entries sits beside it.
# Both are written directly into docs/ rather than handed to the workflow the way audio.mp3 is:
# there is no manifest to keep honest here (a deck entry only claims audio that was actually
# written), and `git add docs/` in briefing.yml already stages additions AND deletions.
LESSONS_PATH = os.path.join(DOCS_DIR, "lessons.json")
LESSON_AUDIO_DIR = os.path.join(DOCS_DIR, "lessons")
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
