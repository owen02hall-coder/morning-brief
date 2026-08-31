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
- **Owen's Alphabet Soup** — one thing worth knowing for life, last on the page and last in the
  audio: money mechanics, home/car repair, health and emergencies, or how judgement and persuasion
  go wrong, rotating evenly. Every lesson is written from a real article that is fetched first (the
  model never writes from memory), an invented figure or year discards it, and it carries the source
  link. Pick Quick / Medium / Long on the phone. **A new lesson only comes up when you actually
  finish the briefing, or when you tap "New lesson"** — leave it half-listened and it is still there
  tomorrow
- **Listen** — a daily audio edition (Gemini TTS) with lock-screen/CarPlay controls: must-knows,
  percent moves, then the 10-year Treasury, the 30-year mortgage and the VIX with the reason behind
  each and an overall read on the market, then tech and world (a story filed in both is read once),
  and on Mondays a digest of the week's policy that affects you. The day's Alphabet Soup lesson
  plays straight after it as one queue; falls back to the phone's built-in voice offline, on
  archived briefings, or on a failed-TTS day
- **Health and science** — findings worth knowing: trial results, outbreaks, safety findings,
  genuine discoveries. Not the politics of science funding
- **Across the country** — big US national news: what happened and what it means, never the
  partisan argument about it. Sourced from AP and NPR National
- **Market breadth** — % of S&P 500 and Nasdaq-100 members above their 200-day average, computed
  daily (validated against the published $S5TH/$NDTH indexes), with two alert tiers per index: a
  one-shot warning when breadth falls below 40% and a daily high-priority oversold nag below 30%
- Searchable archive of past briefings + a Sunday weekly recap
- A morning "ready" push sent only AFTER the new edition is actually published, plus a
  self-monitoring health ping if a run fails or degrades

## How it works

```
GitHub Actions (daily cron, UTC) --> python -m scripts.build_briefing
  Yahoo Finance chart API, keyless (S&P 500, Nasdaq Composite, VIX, 10-yr)  +  RSS feeds (news)
  --> Gemini writes a structured, cited briefing  (numbers injected as facts, never invented)
  --> Alphabet Soup: Gemini names an article, Wikipedia is FETCHED, Gemini writes the lesson from
      it, code checks the prose back against that text  (no article -> no lesson that day)
  --> scripts/tts.py narrates it + Gemini TTS synthesizes; lameenc encodes the mp3 in-process
  --> writes docs/briefing.json + archive + state + docs/lessons.json (+ lesson clips); workflow
      publishes docs/briefing-audio.mp3 (+ a date manifest, written only on success) and commits
  --> GitHub Pages serves the PWA; ntfy pushes "ready" only after git push succeeded
PWA (docs/) reads briefing.json + lessons.json (network-first), renders it, plays the Listen queue
(today's mp3 -> the current lesson's clips -> sign-off) when the audio manifest matches today
(device-voice fallback otherwise), archive + freshness banner. Which lesson is current lives in the
phone's localStorage, because only the phone knows whether the audio actually reached the end.
```

Supply-chain hardening: workflows install with a CI-frozen `constraints.txt` and pin actions by
commit SHA; `shell-guard.yml` fails any push that changes the PWA shell without a service-worker
CACHE bump (installed clients would otherwise never update — this shipped broken once).

## One-time setup

### 1. Free accounts / keys
- GitHub account (hosts the code + runs the job + serves the page).
- Google Gemini API key — https://aistudio.google.com/apikey (free; keep the project's billing OFF).
- ntfy app on your phone — https://ntfy.sh/ → install, then subscribe to a private topic name
  you choose (the topic name is effectively the password — make it long and unguessable, e.g.
  `briefing-<random>`).
(No other keys needed — market numbers and breadth both come from keyless sources.)

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
built — plus the regression gates for the policy and lesson sections. Two of them need nothing at
all and are worth running after any edit to the lesson feature:

```bash
BRIEFING_SMOKE_ALLOW_DEV=true PYTHONPATH=. python scripts/briefing-assumptions/10-lesson-sources.py
BRIEFING_SMOKE_ALLOW_DEV=true node scripts/briefing-assumptions/11-client-pointer.js
``` Note what they do NOT cover: the v1 market source itself (Yahoo's chart API) — the suite
predates the FRED→Yahoo move.

Re-running the full suite needs no packages beyond requirements.txt — only keys:
`TWELVEDATA_API_KEY` (tests 1–2, v2 key) and `GEMINI_API_KEY` (tests 3 and 6). The runner halts at
the first test missing its key. The keyless boundary test runs on its own:

```bash
# everything (needs both keys):
BRIEFING_SMOKE_ALLOW_DEV=true bash scripts/briefing-assumptions/run-all.sh
# just the keyless RSS/boundary check (no key, no extra deps):
BRIEFING_SMOKE_ALLOW_DEV=true python scripts/briefing-assumptions/04-external-boundary-smoke.py
```

Until 2026-08-31 both of those commands also required `pip install pandas lxml`, which is why 04
exited 3 INFRA on its first scheduled CI run: pandas is deliberately not a dependency of this
project, so the test could never run on a runner. It now uses the shipping stdlib parser. Test 01
still carries the same `pandas` import, and is excluded from CI for unrelated reasons (metered
Twelve Data quota) — install pandas by hand if you ever run it.
