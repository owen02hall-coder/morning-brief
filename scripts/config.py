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
# All four headline numbers come from FRED's keyless CSV (prior-close, day-over-day). We request
# only a short recent window (cosd) so payloads stay tiny and fast. "Nasdaq" = the Nasdaq Composite
# (NASDAQCOM); the Nasdaq-100 index is not on a free tier (Twelve Data free excludes indices), and
# the Composite is the standard free "Nasdaq" proxy for an overview.
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={cosd}"
FRED_SERIES = {"sp500": "SP500", "ndx": "NASDAQCOM", "vix": "VIXCLS", "ten_year": "DGS10"}
FRED_WINDOW_DAYS = 45            # only the last ~45 days; enough for the last two observations
FRED_TIMEOUT = 45               # FRED can be slow; generous timeout + one retry in market.py

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
