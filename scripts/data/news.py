"""Fetch + parse RSS feeds into recent candidate items, isolated per-feed.

Returns three buckets (world, business, tech) of {title, source, url, summary, published}.
A dead feed is tolerated (logged, skipped) so one outage never kills the briefing. Items older
than NEWS_WINDOW_HOURS are dropped; near-duplicate titles/URLs are de-duped; each bucket is capped.
"""
import urllib.request
from calendar import timegm
from datetime import datetime, timezone, timedelta

import feedparser

from .. import config


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def _norm(s):
    return " ".join((s or "").lower().split())


def _published(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return datetime.fromtimestamp(timegm(t), timezone.utc)


def _bucket(feeds):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.NEWS_WINDOW_HOURS)
    items, seen = [], set()
    for source, url in feeds.items():
        try:
            parsed = feedparser.parse(_fetch(url))
        except Exception:
            continue  # per-feed isolation
        for e in parsed.entries:
            pub = _published(e)
            if pub is None or pub < cutoff:
                continue
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            key = _norm(title)[:80] or link
            if key in seen:
                continue
            seen.add(key)
            summary = (e.get("summary") or "").strip()
            items.append({
                "title": title,
                "source": source,
                "url": link,
                "summary": summary[:500],
                "published": pub.isoformat(),
            })
    items.sort(key=lambda x: x["published"], reverse=True)
    return items[: config.MAX_CANDIDATES_PER_BUCKET]


def get_news():
    """Return {world, business, tech, available} candidate lists for the summarizer."""
    world = _bucket(config.WORLD_FEEDS)
    business = _bucket(config.BUSINESS_FEEDS)
    tech = _bucket(config.TECH_FEEDS)
    return {
        "world": world,
        "business": business,
        "tech": tech,
        # world news must always ship; treat empty world as unavailable
        "available": {"world": bool(world), "business": bool(business), "tech": bool(tech)},
    }
