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
BREADTH_MIN_MATCH = 480          # of ~503 constituents; fewer = shape drift -> fail closed
SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
BREADTH_OVERSOLD = 30            # alert enters below this
BREADTH_CLEAR = 33               # alert clears at/above this (hysteresis; no 30/31 flapping)
BREADTH_EXTREME = 20             # flagged as extreme in the alert text
BREADTH_STALE_TRADING_DAYS = 2   # nag suppressed when the value is older than this many trading days

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
STATE_PATH = os.path.join(REPO_ROOT, "state", "state.json")
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
