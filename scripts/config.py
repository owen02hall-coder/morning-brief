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

# --- Notifications / hosting ------------------------------------------------
# Public Pages URL of the PWA; set as an env var/secret at deploy time.
PAGES_URL = os.environ.get("PAGES_URL", "https://example.github.io/morning-briefing/")
NTFY_BASE = "https://ntfy.sh"

# --- Paths ------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
ARCHIVE_DIR = os.path.join(DOCS_DIR, "archive")
BRIEFING_PATH = os.path.join(DOCS_DIR, "briefing.json")
STATE_PATH = os.path.join(REPO_ROOT, "state", "state.json")

# --- Monitoring -------------------------------------------------------------
STALE_HOURS = 28                     # client: the PWA shows "couldn't refresh" past this age
HEARTBEAT_STALE_HOURS = 30           # server: heartbeat.yml pages if the LIVE page is older than this.
                                     # > 24h + GitHub's worst observed schedule jitter (~9h, on the
                                     # build AND on the heartbeat itself) so a healthy-but-jittery day
                                     # never false-alarms; a real multi-day freeze trips it well within
                                     # a day of going stale. It is a freeze backstop, not a punctuality
                                     # check — do not tighten it toward 24h.
