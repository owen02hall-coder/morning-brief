---
title: Integrations
source_files: [scripts/data/, scripts/breadth/, scripts/summarize.py, scripts/tts.py, scripts/notify.py, scripts/config.py, .github/workflows/]
entry_points: [GEMINI_API_KEY, NTFY_SUB, PAGE_URL]
last_verified: 2026-07-06
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
  percent. The last two SETTLED daily closes give value + day-over-day change; a bar belonging to the
  still-open session (per the payload's `currentTradingPeriod`) is dropped, and with only one settled
  close in the window `change` is `null`, never a fabricated 0.
- Notes: a browser-like User-Agent is required. The client tries the query1 then query2 host and uses
  a short `config.MARKET_TIMEOUT` so a hung source fails fast instead of risking the job timeout.
  Missing/null closes (holidays/gaps) are skipped; any failure degrades that number to None.
- History: v1 originally used FRED's keyless CSV, which went unreachable from CI (and locally); Stooq's
  keyless CSV is now behind a JS anti-bot challenge — Yahoo's chart API was the working keyless source
  that still includes indices.

## TradingView scanner (breadth)

- Used for: market breadth — % of S&P 500 / Nasdaq-100 members above their 200-day MA.
- Auth: none. UNOFFICIAL endpoint — treated accordingly (single daily call, full try/except,
  per-index MIN_MATCH fail-close, last-good cache in state.json).
- Invoked in: `scripts/breadth/percent_above_ma.py` — one POST to
  `https://scanner.tradingview.com/america/scan` for the top `BREADTH_SCAN_LIMIT` (2000) US
  common stocks' `close` + `SMA200`. The `type=stock` filter is load-bearing: without it,
  ~430 ADR/fund rows displace S&P names and coverage collapses below the gate.
- Deliberately NOT via the `tradingview-screener` library — that would add pandas+lxml to the
  push-capable CI job for a one-endpoint JSON call.
- Validated vs published indexes ($S5TH, $NDTH) within <1 point.

## Wikipedia (index constituents)

- Used for: the current S&P 500 (~503) and Nasdaq-100 (~101) member lists that breadth
  intersects against.
- Auth: none; needs the project User-Agent (default UA is blocked).
- Invoked in: `scripts/data/constituents.py`, stdlib regex over each page's `constituents`
  table. NOTE the row shapes differ: S&P tickers are LINKED first cells, Nasdaq-100 tickers are
  PLAIN-TEXT first cells. Fail-closed on implausible counts (450–520 / 90–110).

## Google Gemini

- Used for: writing the briefing prose (tldr, the why lines, tech and world items, weekly recap),
  and synthesizing the daily audio edition (`scripts/tts.py`, model `TTS_MODEL` =
  `gemini-2.5-flash-preview-tts`, voice `TTS_VOICE` = Kore, one request/day; mp3 encoded
  in-process with `lameenc`).
- Auth: env var `GEMINI_API_KEY`. Free tier. Keep the Google project's billing disabled to stay free.
- Invoked in: `scripts/summarize.py` via the `google-genai` SDK (`genai.Client`).
- Model: `config.MODEL_ID` (`gemini-2.5-flash`) with `config.MODEL_FALLBACK` (`gemini-2.5-flash-lite`).
  Structured output uses `response_mime_type="application/json"` plus a `response_schema`.
- Privacy: on the free tier Google may use submitted content and output to improve products, and
  human reviewers may see it. Only public news is sent. No personal data. No secrets.
- Resilience: the call tries the primary model then the fallback. If both fail the pipeline writes a
  no-AI briefing (raw numbers plus headlines).

## ntfy

- Used for: the morning "ready" push (sent by the workflow ONLY after `git push` succeeds — see
  `python -m scripts.notify ready`), two-tier market-breadth alerts per index (one-shot warning
  below 40%, daily high-priority oversold nag below 30%), and self-monitoring health pings.
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

## Twelve Data (unused)

- Used for: nothing. It was staged for v2 breadth, but v2 shipped keyless via the TradingView
  scanner instead. `scripts/data/twelvedata.py` is kept only as a possible future source; no
  workflow maps its key.

## Environment variables and GitHub config (names only)

The code reads env vars; the workflows source those from GitHub secrets/variables, whose names differ
for ntfy, Pages, and Twelve Data. Configure the GitHub name; the workflow maps it to the env var.

| GitHub secret/variable | Env var the code reads | Scope |
| --- | --- | --- |
| Secret `GEMINI_API_KEY` | `GEMINI_API_KEY` | v1, required |
| Secret `NTFY_SUB` | `NTFY_TOPIC` | v1, required for notifications |
| Variable `PAGE_URL` | `PAGES_URL` | v1, tap-through link + heartbeat target |
| Secret `TWELVE_API_KEY` | `TWELVEDATA_API_KEY` | unused (client staged only) |
| (none) | `MODEL_ID` | optional Gemini text-model override |
| (none) | `TTS_MODEL` / `TTS_VOICE` | optional audio-edition overrides |

A name mismatch is no longer fully silent: both workflows FAIL FAST at startup when
`secrets.NTFY_SUB` is empty (a missing topic would disable every alarm path), and `config.py`
falls back to the placeholder even when `PAGES_URL` arrives as an empty string (unset repo
variable). The mapping lives in `briefing.yml` and `heartbeat.yml`.

## Supply-chain posture

The daily job holds a write token plus the Gemini/ntfy secrets, so its inputs are pinned:
`requirements.txt` is exact-pinned, transitives are locked by a CI-frozen `constraints.txt`
(refresh: copy the "Successfully installed" line from a green run after changing requirements),
and all actions are pinned by commit SHA. `shell-guard.yml` and `data-smoke.yml` are the
fail-closed/diagnostic guards.
