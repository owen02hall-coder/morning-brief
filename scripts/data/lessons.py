"""Source material for Owen's Alphabet Soup: fetch a real encyclopedia article to teach FROM.

This module exists so the lesson section can be honest. Everything else in the briefing summarises
something that was fetched; a "useful fact of the day" written straight out of a language model is
the one section that would have no source at all behind it, and a confident wrong fact about a
breaker panel or a stroke symptom is worse than no section. So the order is inverted from how a
"daily fact" feature is usually built: **the article is fetched first, and the lesson is written
only from what came back.** No article, no lesson that day.

English Wikipedia's action API is the source: keyless, stable, one request a day, and it returns a
plain-text extract that can be handed to a model as untrusted material exactly the way
`news.py`'s article summaries and `policy.py`'s document abstracts already are.

WHAT IS CHECKED HERE, before a single token is spent:

- `missing` / `invalid` — the model proposed a title that does not exist. Fails to the next
  candidate, never to a search. A near-miss article is worse than none: it would still be a real
  fetched source, so every downstream guard would pass while the lesson taught the wrong subject.
- disambiguation pages — real, long, and about nothing. `pageprops.disambiguation` is the flag.
- `LESSON_MIN_SOURCE_CHARS` — a stub leaves the model nothing to work from but its own memory,
  which is the single thing this design exists to prevent.

`fetch_article()` raises nothing the caller has to think about beyond transport errors: a miss is
None, and `first_usable()` walks a candidate list until one answers.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from .. import config
from . import retry

# Wikipedia asks automated clients to identify themselves with a contact-bearing UA and throttles
# generic ones. Module-local (not config.USER_AGENT) for the same reason mortgage.py and market.py
# keep theirs local: a per-source quirk belongs next to the code that has the quirk.
#
# THE CONTACT IS LOAD-BEARING, NOT DECORATION. Until 2026-08-31 this string ended in a bare
# "https://github.com/" — a hostname with no repo and no address, which Wikimedia's User-Agent
# policy treats as unidentified. The effect is rate-limit class, not a block: at a slow trickle the
# generic UA is let through, but the lesson leg fetches candidates in a tight burst and under burst
# Wikimedia throttled it to 100%. Measured 2026-08-31, 12 distinct titles, alternating order, no
# sleeps: generic UA 429 on 12/12, this UA 200 on 12/12. That is what killed Owen's Alphabet Soup
# for days and produced the "degraded sections: alphabet soup" push.
#
# So: keep a real repo URL and a real contact address here. 14-wikipedia-ua.py asserts that shape
# AND re-measures the burst, because the failure is silent-ish (one low-priority ping that does not
# name a cause) and a future edit could re-generalise the string without anything going red.
WIKI_UA = ("morning-brief/1.0 (https://github.com/owen02hall-coder/morning-brief; "
           "owen02hall@gmail.com) python-urllib/3.12")


def _get(params):
    url = config.WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": WIKI_UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=config.WIKI_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_article(title):
    """Return {title, url, extract} for an English Wikipedia article, or None if unusable.

    None covers all four unusable shapes (missing, invalid, disambiguation, too short) and each one
    logs its reason — the caller tries several candidates in a row, so an undifferentiated "no
    article" would make "the model named three fake pages" and "Wikipedia is unreachable" look
    identical in the job log.

    `redirects=1` is deliberate: "Heimlich maneuver" is a redirect to "Abdominal thrusts", and
    resolving it server-side means the citation URL points at the article that was actually read.
    """
    if not (title or "").strip():
        return None
    data = retry.call(f"Wikipedia ({title})", lambda: _get({
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "redirects": 1,
        "prop": "extracts|pageprops|info",
        "inprop": "url",
        "explaintext": 1,          # plain text, not HTML — nothing to strip, nothing to smuggle
        "exsectionformat": "plain",
        "titles": title,
    }))
    pages = ((data or {}).get("query") or {}).get("pages") or []
    if not pages:
        print(f"lesson: no page object for {title!r}")
        return None
    page = pages[0]
    if page.get("missing") or page.get("invalid"):
        print(f"lesson: article {title!r} does not exist — trying the next candidate")
        return None
    if (page.get("pageprops") or {}).get("disambiguation") is not None:
        print(f"lesson: article {title!r} is a disambiguation page — trying the next candidate")
        return None
    extract = (page.get("extract") or "").strip()
    if len(extract) < config.LESSON_MIN_SOURCE_CHARS:
        print(f"lesson: article {title!r} is a stub ({len(extract)} chars < "
              f"{config.LESSON_MIN_SOURCE_CHARS}) — trying the next candidate")
        return None
    url = page.get("fullurl") or ("https://en.wikipedia.org/wiki/"
                                  + urllib.parse.quote((page.get("title") or title).replace(" ", "_")))
    return {"title": page.get("title") or title, "url": url, "extract": extract}


def first_usable(titles, already_taught):
    """Walk `titles` in order and return the first article that fetches and has not been taught.

    `already_taught` is the set of canonical article titles from state (`lessons_taught`), checked
    AFTER the fetch rather than before: redirects mean "Heimlich maneuver" and "Abdominal thrusts"
    are the same lesson, and only the fetch knows that. Checking the proposed string alone would let
    the same article ship twice under two names.

    A transport failure on one candidate is logged and skipped, not raised — the next candidate is a
    free second chance, and the caller's own fallback (config.LESSON_SEED_ARTICLES) is behind that.

    ONE EXCEPTION: a 429 ends the walk immediately. The candidates are not independent when the
    failure is a rate limit — the limiter is keyed on this client, not on the title, so title N+1 is
    guaranteed to get the same answer title N just got. On 2026-08-31 that guarantee played out
    exactly: 16 candidates, 16 x 429, and the first two burned the whole process-global retry budget
    (retry.py sizes RETRY_EXTRA_ATTEMPT_BUDGET for a documented 12-request policy/mortgage surface
    that never counted this leg) so the other fourteen ran unprotected. Walking on costs the budget
    the policy section needs, costs wall-clock inside a 10-minute job, and cannot succeed. Stopping
    also makes the log say "rate-limited" once instead of hiding it under sixteen identical lines.
    """
    taught = {(t or "").strip().lower() for t in (already_taught or [])}
    for title in titles or []:
        try:
            article = fetch_article(title)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"lesson: RATE-LIMITED by Wikipedia on {title!r} (HTTP 429) — abandoning the "
                      f"walk; every remaining candidate would get the same answer. Check WIKI_UA "
                      f"against Wikimedia's User-Agent policy: an unidentified UA is throttled "
                      f"under burst and that is what this looks like.")
                return None
            print(f"lesson: fetch failed for {title!r} ({type(e).__name__}: {e}) — next candidate")
            continue
        except Exception as e:
            print(f"lesson: fetch failed for {title!r} ({type(e).__name__}: {e}) — next candidate")
            continue
        if not article:
            continue
        if article["title"].strip().lower() in taught:
            print(f"lesson: {article['title']!r} was already taught — next candidate")
            continue
        return article
    return None
