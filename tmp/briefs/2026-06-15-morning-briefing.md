# Brief: Personal morning news/market briefing (PWA + daily Claude routine)

## Why
The user wants a single, simple "daily information upload" to read each morning: what the
market did and *why* (up or down), explained in a few plain-English sentences with a
"read more" option and cited sources. Plus a finger on the pulse of emerging/cutting-edge
technology, and what changed in the world overnight. It must be effortless to glance at on
a phone. A specific, concrete trigger started the conversation: monitor the StockCharts
Bullish Percent Indices ($BPSPX for S&P 500, $BPNDX for Nasdaq-100) and get nagged daily
when either drops below 35% (an oversold breadth signal) until it recovers.

## Context
- **Greenfield project.** Working dir `c:\Users\User\Desktop\AI CODE\News` is not a git repo
  yet and currently has no app code. This is a fresh build.
- **Hard cost constraint:** user has a Claude *subscription* but will not spend additional
  money. Key distinction surfaced in discussion: a subscription is NOT the Claude API. A
  conventional "backend calls an LLM every morning" would incur API cost and is rejected.
- **Engine verification (load-bearing, done via claude-code-guide):** A scheduled cloud
  routine CAN technically do everything needed — run unattended on cron at a set time/timezone
  (Anthropic cloud, user's PC can be off), use WebSearch/WebFetch + Bash, make outbound HTTP
  (ntfy — note: network is disabled by default and must be explicitly enabled/allow-listed),
  push to GitHub (via a PAT held in a Vault), and **persist day-to-day state via a Memory Store**
  (e.g. `/mnt/memory/state.json`) which is exactly how the nag-alert remembers it's mid-alert.
  **BUT the billing model is NOT documented** — the underlying "managed agents" system appears to
  be metered per-token and may NOT be covered by the Pro/Max subscription. So the $0 claim for the
  CLOUD engine is UNVERIFIED. See the engine decision + clash below.
- **StockCharts feasibility finding (load-bearing):** Live values at
  `https://stockcharts.com/sc3/ui/?s=%24BPSPX` and `...=%24BPNDX` are rendered client-side via
  JavaScript. A plain HTTP fetch returns only the page shell (title "SharpCharts | StockCharts.com"),
  no number. $BPSPX/$BPNDX are StockCharts' proprietary calculations with no free public API and
  are not syndicated to Yahoo/Google. Therefore the value must be either scraped via a headless
  browser (fragile + against StockCharts ToS) or **computed independently** (chosen).
- **Bullish Percent Index definition:** % of constituents in an index currently on a Point &
  Figure "buy" signal. Computable from daily OHLC of the index constituents. Replicating
  StockCharts' exact P&F box-sizing is finicky, so our number will track closely but not match
  to the decimal — drives the "buffer zone" decision below.
- **Free data sources (REVISED — confidence pass):** market data = **Twelve Data free tier**
  (800 credits/day, API key, works from CI). Yahoo/`yfinance` was DROPPED — it is IP-blocked from
  GitHub Actions runners (documented 429-on-first-call from datacenter IPs, 2025-2026), which would
  have broken the breadth feature. Stooq also dropped (anti-bot wall). Constituent lists from
  Wikipedia. News from RSS feeds.
- **News/summarization:** Claude's built-in web search inside the scheduled routine (free under
  subscription) does both the searching and the plain-English summarization with sources.

## Decisions
- **Delivery = PWA** ("Add to Home Screen"), works iPhone + Android — chosen over a true native
  app (App Store/build overhead not worth it for a single-user v1) and over email/Telegram-only
  (user wants an app-like daily read). Can go native later.
- **Engine = GitHub Actions (scheduled workflow) + a free AI tier (Google Gemini free tier).**
  FINAL. A daily GitHub Actions cron runs in GitHub's cloud — laptop/phones can all be OFF — pulls
  live data, fetches fresh news, has the free AI write the grounded briefing, commits the artifact
  (so GitHub Pages updates), and POSTs to ntfy. Truly free, no hardware, nothing to babysit, one
  account (GitHub also hosts the PWA). The AI being Gemini rather than Claude is acceptable to the
  user — accuracy is independent of AI brand (see accuracy decision). Known minor caveats: scheduled
  Actions can run ~10-20 min late at peak, and pause after 60 days of zero repo activity (a daily
  commit keeps it alive).
- **Accuracy strategy (user's #1 priority) — accuracy lives in the plumbing, not the AI brand:**
  (a) all NUMBERS (index moves, VIX, 10-yr yield, breadth) come directly from live market-data
  feeds and are exact by construction — the AI never invents a number, only explains ones it's given;
  (b) the AI summarizes ONLY fresh articles/data we fetch that same morning and cites only those real
  URLs — never its own memory, never invented links. This guarantees "up to date" regardless of the
  model's training cutoff.
- **Run time / timezone = ~6am Mountain Time (America/Denver, user is in Utah).** Good fit: US
  markets close 2pm MT, so prior-day data is fully settled plus early pre-market is visible.
  (GitHub Actions cron is in UTC; convert + handle DST.)
- **Day-to-day state = a state file committed in the git repo** (e.g. `state.json`). Holds alert
  status (mid-nag? recovered?) and "yesterday" context so the nag logic and continuity work across
  runs. Each run reads it, updates it, commits it.
- **Weekend/holiday + missing-data rule (per user):** never skip a day. For any section whose data
  isn't available (markets closed, source down), explicitly say "information not available" for that
  piece, and STILL deliver the overall world-news summary (and tech). No silent gaps.
- **Failure/staleness handling:** if a refresh fails, the PWA shows a plain "couldn't refresh —
  last updated [date]" notice rather than silently presenting stale content as current.
- **Source integrity:** the AI must cite only URLs it actually fetched during the run — never invent
  or guess a source. Sources are a core user requirement.
- **Privacy (accepted):** free GitHub Pages is typically a *public* URL and the ntfy topic is
  guessable — the briefing is effectively world-readable. Acceptable for v1 since it carries no
  personal data (no watchlist, no accounts). Use an unguessable ntfy topic name to reduce noise.
- **Hosting = GitHub Pages (free).** The routine commits the generated briefing
  (e.g. JSON/markdown) to a repo; GitHub Pages serves the static PWA which renders it.
- **Notifications = ntfy.sh (free, no account).** Handles both the morning drop and the
  `<35%` daily nag-until-recovered. Chosen over PWA web push (iOS web push is finicky/unreliable
  for a recurring nag) and Telegram (avoids a second app; PWA is the read surface).
- **[DEFERRED TO v2 after /script proof, 2026-06-15] Breadth.** Assumption tests proved the
  Twelve Data free tier is 8 credits/min (1/symbol), so a daily 600-constituent pull is not viable
  (~75 min, ~600/800 credits). User approved shipping the CORE briefing first (market, yield, VIX,
  tech, world, AI, notifications — all proven green) and adding breadth + the oversold nag as a
  fast-follow once a 1-call/day whole-market source (e.g. Polygon grouped-daily) is proven. The
  dual-gauge design below stands for v2:
- **Breadth = DUAL gauge (REVISED — confidence pass, user chose "do both"):**
  (1) PRIMARY = **% of constituents above their 200-day moving average** for S&P 500 and Nasdaq-100.
  Simple math (no Point & Figure), reliable, a more standard breadth gauge. Oversold alert at
  **< 30%** (extreme < 20%), the equivalent of the original "< 35" BPI line.
  (2) SECONDARY = **BPSPX/BPNDX (Bullish Percent Index)** computed via P&F from the same Twelve Data
  constituent data, shown when computable, with its own < 35 alert. If the P&F replication is off or
  data is short, the primary gauge still carries the oversold signal.
  Rationale: removes the two biggest risks (yfinance-from-CI and finicky P&F accuracy) from the
  critical path while still delivering the exact StockCharts-style number when possible.
- **Breadth history seeding:** % above 200-day MA needs ~200+ trading days of history; seed once
  locally (or spread the backfill across days within the free quota), then fetch only the daily
  increment in CI.
- **Buffer zone on the alert (confirmed):** because our computed value can be a point or two off
  near the threshold, show "watch / approaching oversold" between 35-37 and "oversold" under 35, so
  an estimation wobble never causes a *missed* signal. Alert + daily nag whenever below 35; stop
  nagging once back above 35.
- **Guiding principle (added in brainstorm): high-level "overall picture" only.** The user
  explicitly does NOT want individual things to watch/track ("I don't have time to watch individual
  stuff, I just want an overall what's going on"). Every section should surface the big picture in a
  glance — avoid granular per-stock, per-event, or per-item tracking.
- **Sections for v1 (final, ordered):**
  (0) **TL;DR top-3** — the 3 must-knows at the very top in one glance, then scroll for depth;
  (1) Market why — what indices did + why, plain English, read-more, source;
  (2) **10-year Treasury yield** — single overall macro number + one-line why;
  (3) VIX — simple value icon + one-line "why it is what it is";
  (4) BPSPX/BPNDX breadth icons + alert;
  (5) Emerging tech / cutting edge;
  (6) Overnight world news, signal-filtered.
- **Archive + search (added):** keep past briefings (cheap given the file-based artifact setup) and
  let the user scroll back / search them.
- **Weekly Sunday recap (added):** on Sundays, also produce a zoom-out recap of the week's big moves
  + what's coming next week. (No cross-day "thread tracking" in v1.)
- **Every item carries a cited source + read-more link.** Non-negotiable per the user. Each item
  is a short few-sentence summary; "read more" expands/links to the full source for depth.
- **No emojis anywhere (user preference).** The briefing, the PWA UI, and notifications must use
  clean, professional plain text — no emoji icons. (Where the design said "icons" for VIX/breadth,
  use text/number indicators or simple non-emoji visual cues, not emoji.)
- **World-news scope (clarified):** only globally significant, overarching events that matter at a
  world level. NOT granular/partisan US politics or hyper-specific stories. Surface the big,
  important things; skip the noise.
- **Source stance (clarified):** no editorial bias and no preferred/blocked outlets — just
  accurate, reliable, diversified mainstream reporting. Goal is correctness and neutrality, not a
  particular viewpoint.
- **No personal watchlist in v1** (overall market only); revisit later.
- **Budget = $0/month** beyond the existing Claude subscription.

### Brainstorm additions explicitly DEFERRED (not v1)
Economic calendar / "what to watch today" / earnings (too granular for the "overall only"
principle); crypto BTC/ETH; Fear & Greed + oil/gold/dollar macro one-liners; read-aloud audio
(phone TTS — free, deferred by user choice); cross-day thread tracking; all personal life-glue
(weather, daily quote, "on this day"). All remain easy future adds.

## Rejected Alternatives
- **True native iOS/Android app** — too much overhead (store review, build tooling, updates) for a
  single-user v1; PWA gives ~95% of the feel.
- **Scraping StockCharts for the exact BPI** — fragile (JS-rendered, breaks on page changes) and
  against their ToS.
- **Conventional API-backed backend** — would cost per-use money; violates the no-extra-spend
  constraint. Replaced by the scheduled-Claude-Code engine (cloud or local).
- **GitHub Actions (or similar) as a free cron** — the cron is free, but the LLM summarization step
  would still need paid API access (it can't use the user's Claude subscription), so it doesn't
  actually solve the cost problem. Rejected.
- **Email-only or Telegram-only delivery** — user specifically wants an app-like morning read.
- **Anthropic `/schedule` cloud routine as the engine** — billing undocumented/possibly metered;
  abandoned in favor of GitHub Actions + free AI tier, which is verifiably free.
- **Local Windows Task Scheduler on the laptop** — user wants it to work when the laptop is OFF, so
  a laptop-bound engine is out.
- **Old phone as an always-on server** — user's old iPhone can't run background jobs (iOS), and an
  old Samsung-as-server is too flaky/unreliable for something depended on every morning.
- **yfinance/Yahoo as the market-data source (confidence pass)** — documented to be IP-blocked from
  GitHub Actions runners (429 on first call from datacenter IPs); replaced by Twelve Data.
- **BPSPX/BPNDX as the SOLE breadth gauge** — kept only as a secondary; the P&F replication is
  finicky and accuracy near the 35 line is unproven, so % above 200-day MA is the reliable primary.

## Where Reasoning Clashed
- **Accuracy vs. robustness on the breadth number.** Scraping gives StockCharts' exact figure;
  computing ourselves is robust/free but approximate near the 35 boundary. A reasonable person
  could prefer the exact scrape. Resolved toward compute-ourselves + a buffer zone, because the
  alert's value is "am I roughly in oversold territory," not a to-the-decimal match, and ToS/
  fragility of scraping outweigh the precision gain for a personal tool.
- **Cloud vs local engine, driven by the unverified billing model.** If the cloud routine is free
  under the subscription, it's strictly better (PC can be off, has a Memory Store). If it's metered,
  the only truly-free option is the local Task Scheduler route — but the user's PC is only sometimes
  on, so the briefing could arrive late. A reasonable person could pick either: pay a small unknown
  cloud fee for reliability, or accept free-but-sometimes-late local. Resolved as "try cloud, verify
  billing, fall back to local" rather than committing blind.

## One Thing to Do First
Stand up the data spine: a small script that, given an index, pulls free daily constituent prices
and prints (a) the computed Bullish Percent Index and (b) the current ^VIX. This proves the
biggest remaining load-bearing risk (free, accurate market data + BPI math) before any GitHub
Actions / Gemini / PWA / ntfy plumbing is built. (Engine is now settled: GitHub Actions + Gemini.)

## Direction
Build a free, single-user **PWA morning briefing** driven by a daily **GitHub Actions** cron that
pulls live market data + fresh news, has a **free AI tier (Gemini)** write a cited, plain-English,
grounded briefing, commits it to a **GitHub Pages**-hosted PWA, and pushes a morning notification
plus a daily **ntfy.sh** nag-alert whenever the self-computed **BPSPX/BPNDX** breadth (safety buffer
near 35) signals oversold. Works with laptop/phones off; accuracy comes from live data feeds +
grounded, cited summarization, not the AI brand. Everything stays high-level/"overall picture"
only. v1 sections: TL;DR top-3, market-why, 10-year yield, VIX, breadth, emerging tech, overnight
world — plus an archive of past briefings and a weekly Sunday recap.
