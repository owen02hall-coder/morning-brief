# Morning Briefing

A free, single-user morning briefing. Every morning a GitHub Actions job pulls market numbers and
fresh news, has Google Gemini write a short cited plain-text summary, publishes it to a GitHub
Pages web app you read on your phone, and sends a push notification via ntfy.

Runs with your laptop and phone off. Cost: $0/month (all free tiers + your existing subscriptions).

## What's in v1

- TL;DR (the 3 must-knows)
- Markets: S&P 500, Nasdaq Composite, 10-year Treasury yield, VIX (latest close, day change, and a plain-English why)
- Emerging tech (a few cutting-edge items, cited)
- World news (globally significant only, cited)
- Searchable archive of past briefings + a Sunday weekly recap
- A morning "ready" push, plus a self-monitoring health ping if a run fails or degrades

Breadth / oversold-alert (BPSPX-style) is a planned v2 fast-follow — see
`tmp/ready-plans/` for the design and why it was deferred (free market-data rate limits).

## How it works

```
GitHub Actions (daily cron, UTC) --> python -m scripts.build_briefing
  Yahoo Finance chart API, keyless (S&P 500, Nasdaq Composite, VIX, 10-yr)  +  RSS feeds (news)
  --> Gemini writes a structured, cited briefing  (numbers injected as facts, never invented)
  --> writes docs/briefing.json + docs/archive/<date>.json + state/state.json, commits them
  --> GitHub Pages serves the PWA; ntfy pushes "ready"
PWA (docs/) reads briefing.json (network-first), renders it, shows an archive + freshness banner
```

## One-time setup

### 1. Free accounts / keys
- GitHub account (hosts the code + runs the job + serves the page).
- Google Gemini API key — https://aistudio.google.com/apikey (free; keep the project's billing OFF).
- ntfy app on your phone — https://ntfy.sh/ → install, then subscribe to a private topic name
  you choose (the topic name is effectively the password — make it long and unguessable, e.g.
  `briefing-<random>`).
- (v2 only) A Twelve Data API key — https://twelvedata.com/ — will be needed when the breadth /
  oversold feature is added. NOT required for v1.

### 2. Create a public repo and push this code
A public repo is required for free GitHub Pages + unlimited Actions minutes. The page is
world-readable; it contains only public news, so that is fine.

### 3. Turn on GitHub Pages
Repo Settings -> Pages -> Source = "Deploy from a branch" -> Branch = `main`, folder = `/docs`.
Your site will be at `https://<your-user>.github.io/<repo>/`.

### 4. Add secrets and a variable
Repo Settings -> Secrets and variables -> Actions:
- Secret `GEMINI_API_KEY`
- Secret `NTFY_SUB` — your chosen ntfy topic name (the workflows map this into the `NTFY_TOPIC` env var)
- Variable `PAGE_URL` = your Pages URL from step 3 (mapped into the `PAGES_URL` env var; lets the
  notification and the heartbeat reach your page)

(`TWELVEDATA_API_KEY` is only needed for the v2 breadth feature, not v1.)

### 5. Run it once
Actions tab -> "Morning Briefing" -> "Run workflow" (leave "force" on). It builds today's
briefing, commits it, and pushes a notification. Then open your Pages URL on your phone and use
Share -> "Add to Home Screen".

## Data privacy

The briefing runs on Gemini's free tier, where Google may use submitted content (public news) and
generated output to improve its products, and human reviewers may see it. No personal data is sent.
Do not put secrets in any input. Keep the Gemini key on a billing-disabled project to stay free.

## Run locally (dev)

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=... NTFY_TOPIC=...   # PowerShell: $env:NAME="..."
python -m scripts.build_briefing --spine               # print market numbers + news counts (no key needed)
python -m scripts.build_briefing --local --no-notify   # write docs/briefing.json, no push
```

## Assumption tests

`scripts/briefing-assumptions/` holds the pre-flight tests that proved the news/RSS boundary,
the Gemini structured-output contract, and the (v2-only) Twelve Data budget before this was
built. Note what they do NOT cover: the v1 market source itself (Yahoo's chart API) — the suite
predates the FRED→Yahoo move.

Re-running the full suite needs dev-only extras and keys beyond requirements.txt: `pip install
pandas lxml`, plus `TWELVEDATA_API_KEY` (tests 1–2, v2 key) and `GEMINI_API_KEY` (test 3); the
runner halts at the first test missing its dependency. The keyless boundary test runs on its own:

```bash
# everything (needs pandas+lxml and both keys):
BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh
# just the keyless RSS/boundary check (still needs pandas+lxml):
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/04-external-boundary-smoke.py
```
