---
title: Integrations
source_files: [scripts/data/market.py, scripts/data/news.py, scripts/summarize.py, scripts/notify.py, scripts/config.py, .github/workflows/briefing.yml]
entry_points: [GEMINI_API_KEY, NTFY_SUB, PAGE_URL, TWELVE_API_KEY]
last_verified: 2026-06-22
---

# Integrations

All external services are free tiers. Secrets are passed as environment variables. No credential
values live in the repo. Environment variable names only are listed here.

## Yahoo Finance (chart API)

- Used for: the four headline market numbers (S&P 500, Nasdaq Composite, VIX, 10-year Treasury yield).
- Auth: none. Keyless chart endpoint (unlike most free tiers, it includes indices).
- Invoked in: `scripts/data/market.py` (`_yahoo_series`).
- Endpoint shape: `https://<query1|query2>.finance.yahoo.com/v8/finance/chart/<SYMBOL>?range=5d&interval=1d`.
- Symbols: `^GSPC`, `^IXIC`, `^VIX`, `^TNX` (see `config.YAHOO_SYMBOLS`); `^TNX` is the 10-yr yield in
  percent. The last two daily closes give value + day-over-day change.
- Notes: a browser-like User-Agent is required. The client tries the query1 then query2 host and uses
  a short `config.MARKET_TIMEOUT` so a hung source fails fast instead of risking the job timeout.
  Missing/null closes (holidays/gaps) are skipped; any failure degrades that number to None.
- History: v1 originally used FRED's keyless CSV, which went unreachable from CI (and locally); Stooq's
  keyless CSV is now behind a JS anti-bot challenge — Yahoo's chart API was the working keyless source
  that still includes indices.

## Google Gemini

- Used for: writing the briefing prose (tldr, the why lines, tech and world items, weekly recap).
- Auth: env var `GEMINI_API_KEY`. Free tier. Keep the Google project's billing disabled to stay free.
- Invoked in: `scripts/summarize.py` via the `google-genai` SDK (`genai.Client`).
- Model: `config.MODEL_ID` (`gemini-2.5-flash`) with `config.MODEL_FALLBACK` (`gemini-2.5-flash-lite`).
  Structured output uses `response_mime_type="application/json"` plus a `response_schema`.
- Privacy: on the free tier Google may use submitted content and output to improve products, and
  human reviewers may see it. Only public news is sent. No personal data. No secrets.
- Resilience: the call tries the primary model then the fallback. If both fail the pipeline writes a
  no-AI briefing (raw numbers plus headlines).

## ntfy

- Used for: the morning "ready" push and a self-monitoring health ping.
- Auth: none. The topic name is the access control, so it must be long and unguessable.
- Config: the code reads env var `NTFY_TOPIC`; the GitHub secret is named `NTFY_SUB` and the
  workflows map `secrets.NTFY_SUB -> NTFY_TOPIC`. Invoked in `scripts/notify.py` (POST to
  `https://ntfy.sh/<topic>`). If `NTFY_TOPIC` is unset every push is silently skipped.
- Headers used: Title, Priority, Click (the tap-through URL). The morning push taps through to
  `PAGES_URL`.
- Privacy note: anyone who knows the topic can read and publish to it. This is acceptable for a
  single user with no personal data, but the topic must not be shared.

## RSS news feeds

- Used for: world, business, and tech candidate articles fed to the summarizer.
- Auth: none. Parsed with `feedparser` in `scripts/data/news.py`.
- Feed lists: `config.WORLD_FEEDS`, `config.BUSINESS_FEEDS`, `config.TECH_FEEDS`.
- Current feeds: BBC World, Al Jazeera, Guardian World, NPR (world); MarketWatch, Yahoo Finance,
  CNBC (business); Ars Technica, The Verge, MIT Technology Review, Hacker News (tech).
- Notes: each feed is fetched in a try/except so one outage cannot abort the run. Items older than
  `config.NEWS_WINDOW_HOURS` are dropped. Titles and URLs are de-duped. Each bucket is capped.

## GitHub Pages and GitHub Actions

- Used for: hosting the PWA (Pages) and running the daily job (Actions).
- Auth: the built-in `GITHUB_TOKEN` pushes the daily commit. No personal access token.
- Config: the code reads env var `PAGES_URL` (the public site URL, used in the notification Click
  header and by the heartbeat); the GitHub repo variable is named `PAGE_URL` and the workflows map
  `vars.PAGE_URL -> PAGES_URL`. If unset it falls back to a placeholder URL.
- Notes: the repo must be public for free Pages and unlimited Actions minutes. Pages serves from
  branch `main`, folder `/docs`.

## Twelve Data (v2 only)

- Used for: nothing in v1. Staged for v2 breadth (per-constituent quotes).
- Auth: the client reads env var `TWELVEDATA_API_KEY`; the GitHub secret is named `TWELVE_API_KEY`
  (a v2 workflow will map `secrets.TWELVE_API_KEY -> TWELVEDATA_API_KEY`). Free tier limit is 8
  credits per minute and 800 per day.
- Client: `scripts/data/twelvedata.py`. Not imported by the v1 pipeline.
- Reason it is not used in v1: the free tier gates index symbols, and a daily 600-constituent pull
  exceeds the per-minute limit. v1 uses the keyless Yahoo Finance chart API instead.

## Environment variables and GitHub config (names only)

The code reads env vars; the workflows source those from GitHub secrets/variables, whose names differ
for ntfy, Pages, and Twelve Data. Configure the GitHub name; the workflow maps it to the env var.

| GitHub secret/variable | Env var the code reads | Scope |
| --- | --- | --- |
| Secret `GEMINI_API_KEY` | `GEMINI_API_KEY` | v1, required |
| Secret `NTFY_SUB` | `NTFY_TOPIC` | v1, required for notifications |
| Variable `PAGE_URL` | `PAGES_URL` | v1, tap-through link + heartbeat target |
| Secret `TWELVE_API_KEY` | `TWELVEDATA_API_KEY` | v2 only |
| (none) | `MODEL_ID` | optional Gemini model override |

A name mismatch is silent: `notify.py` skips the push when `NTFY_TOPIC` is empty, and `PAGES_URL`
falls back to a placeholder. The mapping lives in both `briefing.yml` and `heartbeat.yml`.
