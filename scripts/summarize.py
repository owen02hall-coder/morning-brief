"""Turn market numbers + fetched articles into a plain-text, cited briefing via Gemini.

Accuracy is enforced by the plumbing, not by trust:
- NUMBERS are injected as facts; the model writes only the 'why' prose, never the figures.
- Every item URL is post-validated IN CODE against the set of URLs we actually fetched; any
  invented link is dropped. A prompt instruction is a label, not a mechanism.
- If Gemini fails or returns an unusable object, the caller falls back to a no-AI briefing.

Proven (see scripts/briefing-assumptions/03): gemini-2.5-flash with response_mime_type +
response_schema yields a valid resp.parsed for this schema.
"""
import json

from google import genai
from google.genai import types
from pydantic import BaseModel

from . import config


class Item(BaseModel):
    summary: str
    source: str
    url: str


class Narrative(BaseModel):
    tldr: list[str]
    market_why: str
    yield_why: str
    vix_why: str
    tech: list[Item]
    world: list[Item]
    weekly_recap: str | None = None


SYSTEM = (
    "You are a precise financial and world-news editor writing one person's morning briefing. "
    "Use ONLY the provided data and articles. Cite ONLY URLs present in the input; never invent a "
    "source, a link, or a number. Plain professional text. NO emojis anywhere. Each item is a few "
    "sentences, high-level overview only. World news: only globally significant events, not "
    "granular or partisan US politics. Neutral, factual tone. The market figures are the LATEST "
    "available closing values (each carries an 'as of' date) — describe them as the most recent "
    "close in the past tense; never claim they are today's live or intraday levels."
)


def _facts_block(market):
    def fmt(n, unit=""):
        if not n:
            return "unavailable"
        return f"{n['value']}{unit} (change {n['change']:+}{unit}, as of {n['asof']})"
    return (
        f"S&P 500: {fmt(market.get('sp500'))}\n"
        f"Nasdaq Composite: {fmt(market.get('ndx'))}\n"
        f"VIX: {fmt(market.get('vix'))}\n"
        f"10-year Treasury yield: {fmt(market.get('ten_year'), '%')}\n"
    )


def _articles_block(news):
    lines = []
    for bucket in ("world", "business", "tech"):
        for a in news.get(bucket, []):
            lines.append(json.dumps({"bucket": bucket, "title": a["title"], "source": a["source"],
                                     "url": a["url"], "summary": a["summary"]}))
    return "\n".join(lines)


def _allowed_urls(news):
    urls = set()
    for bucket in ("world", "business", "tech"):
        for a in news.get(bucket, []):
            urls.add(a["url"])
    return urls


def _validate_items(items, allowed):
    """Drop any item whose URL was not in the fetched set (kills invented citations)."""
    out = []
    for it in items:
        url = it.url if isinstance(it, Item) else it.get("url", "")
        if url in allowed:
            out.append(it.model_dump() if isinstance(it, Item) else it)
    return out


def _call(model, prompt):
    client = genai.Client()
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Narrative,
        ),
    )
    parsed = getattr(resp, "parsed", None)
    if parsed is None:
        parsed = Narrative.model_validate_json(resp.text)  # fallback parse
    return parsed


def summarize(market, news, is_sunday, recap_context=""):
    """Return (narrative_dict, ok). narrative_dict is None and ok False if Gemini is unusable."""
    prompt = (
        "Write today's briefing as structured JSON.\n\n"
        f"MARKET FACTS (use verbatim, do not restate numbers in prose, only explain them):\n{_facts_block(market)}\n"
        "Write market_why / yield_why / vix_why as the reasons behind those moves, drawn from the "
        "business articles below.\n\n"
        f"ARTICLES (one JSON per line; cite only these URLs):\n{_articles_block(news)}\n\n"
        "Produce: tldr (at most 3 bullets, the must-knows), market_why, yield_why, vix_why, "
        "tech (<=3 items, cutting-edge developments), world (<=3 items, globally significant only)."
    )
    if is_sunday:
        prompt += ("\n\nAlso write weekly_recap: a short zoom-out of the week's big moves and what "
                   "is coming next week, using this context:\n" + (recap_context or "(no prior days)"))

    allowed = _allowed_urls(news)
    for model in (config.MODEL_ID, config.MODEL_FALLBACK):
        try:
            nar = _call(model, prompt)
        except Exception as e:
            print(f"summarize: model {model} failed ({e})")
            continue
        return {
            "tldr": (nar.tldr or [])[:3],
            "market_why": nar.market_why,
            "yield_why": nar.yield_why,
            "vix_why": nar.vix_why,
            "tech": _validate_items(nar.tech, allowed)[: config.MAX_TECH_ITEMS],
            "world": _validate_items(nar.world, allowed)[: config.MAX_WORLD_ITEMS],
            "weekly_recap": nar.weekly_recap if is_sunday else None,
        }, True
    return None, False
