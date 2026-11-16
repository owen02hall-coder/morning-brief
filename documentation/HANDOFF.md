# Handoff: rebuilding the morning briefing inside a bigger project

This is a brief for whoever (person or Claude session) builds the next version of this briefing as
part of a larger app. It is not a porting guide. **Rebuild fresh.** Use this repo
(`owen02hall-coder/morning-brief`) as a reference you can read, not as code to copy over. The value
here is in the decisions and the mistakes already made. Most of the 8,600 lines exist to handle
edge cases that you only discover by running it every day.

Read alongside: `documentation/architecture.md`, `documentation/operations.md` and
`documentation/integrations.md`, which are accurate as of 2026-11.

---

## 1. What exists today (one paragraph)

A GitHub Actions cron job runs `python -m scripts.build_briefing` once a day. It pulls market
numbers from Yahoo (keyless), news from RSS, federal and Utah policy, and a Wikipedia article for a
daily lesson. Gemini (free tier) writes a short cited summary as structured JSON. Gemini TTS
narrates it to an mp3. The job commits `docs/briefing.json` and the audio, GitHub Pages serves a
PWA from `docs/`, and ntfy sends a push only after the publish succeeds. Cost is $0.

## 2. Principles worth keeping (these took the longest to learn)

1. **Numbers come from data, never from the model.** Code computes every figure and injects it as
   a fact. The model only explains. Validators reject prose that contains a $, % or year missing
   from the source text.
2. **Fail closed, per item, and name the gap.** A dead source drops that one item and says so on
   the page. It never shows a stale or invented value. One bad source never kills the day.
3. **Never skip a day.** If the model is down, use the fallback model. If that fails too, ship the
   raw numbers and headlines.
4. **Fence all third-party text.** Everything fetched goes between `BEGIN/END` markers that the
   prompt says to treat as data, not instructions. *This matters much more once email is an input
   (see §4).*
5. **"Ready" fires only after publishing.** The push is sent after `git push` succeeds, so it can
   never point at yesterday's page. Audio has a date manifest so old audio is never paired with a
   new page.
6. **Separate choosing from writing.** For lessons, the model names an article, code fetches it,
   then the model writes from the fetched text. The same pattern fits newsletters: code extracts
   the stories, the model clusters and summarizes them.
7. **One implementation per classification.** The page and the audio read the same published field
   (e.g. watchlist `action`), so they can't disagree.
8. **Assumption tests before building.** Each external boundary (feed shape, API contract, model
   JSON output) was checked with a small script before code depended on it. These live in
   `scripts/briefing-assumptions/`.

## 3. Operational traps already hit (don't hit them again)

- **GitHub cron runs hours late** at the top of the hour. Use odd minutes, several slots, a
  "not before" local hour, and dedupe by date (`state.last_run`).
- **PWA service worker caching:** changing the app shell without bumping the cache version left
  installed phones stuck on old code. A CI guard (`shell-guard.yml`) now enforces it.
- **A guard nobody triggers isn't a guard.** One smoke test sat dead for 22 days because it was
  dispatch-only. Every check needs a schedule or a push trigger.
- **Gemini free tier limits per minute as well as per day.** Space TTS calls about 20s apart and
  set a deadline inside the 10-minute job cap.
- **Gemini preview models get retired.** Keep a model fallback chain and a weekly test that calls
  every model in it.
- **Don't let the push token sit in `.git/config` while untrusted text is parsed**
  (`persist-credentials: false`, then hand it to git only at commit time).
- **State fields that are declared but never written:** this shipped twice. Use one writer function
  per state key.

## 4. New: newsletter ingestion (Exec Sum, Short Squeez, WSJ, etc.)

### Goal
Read the finance/deal newsletters that arrive each morning and produce a "what's actually new"
section: one deduplicated summary across all of them, not one summary per newsletter.

### Current state of the inbox (checked 2026-11-16)
**None of these newsletters currently arrive at the Gmail account.** The last 14 days contain only
promotional mail (Delta, Priceline, H&M and so on). Step zero is subscribing. A dedicated address
or a `+briefing` alias (`you+briefing@gmail.com`) makes filtering trivial.

**Update 2026-11-16:** subscribed. Confirmed sender addresses (from the welcome emails):

| Newsletter | Sender | Cadence |
|---|---|---|
| Exec Sum (Litquidity) | `news@execsum.co` | Weekday mornings, excluding market holidays |
| Short Squeez | `press@shortsqueez.co` | Weekday mornings |
| WSJ morning newsletter | not yet arrived | — |
| Dealhook | not yet arrived | — |

Note that `news@execsum.co` also sends login codes (subject "... is your login code"). The code-side
filter has to skip those, so allowlisting the sender alone is not enough.

### How to get email into a headless cron job
Claude's Gmail connector works in a chat session, but it is **not** available to a GitHub Actions
job. The pipeline needs its own access. Options, simplest first:

| Option | Setup | Notes |
|---|---|---|
| **IMAP + Gmail app password** (recommended) | Turn on 2-step verification, create an app password, store it as a secret | Python stdlib `imaplib` only, no new dependency. Open the mailbox read-only (`EXAMINE`). |
| Gmail API + OAuth refresh token | Google Cloud project, consent screen, `gmail.readonly` scope | Finer scope. In "Testing" mode the refresh token expires every 7 days, so you have to publish the app (unverified is fine for one user). |
| Email-to-RSS bridge (e.g. kill-the-newsletter style) | Subscribe with the bridge's address | Fits the existing RSS code with zero credentials, but a third party then reads your newsletters. |

### Suggested pipeline shape
```
Gmail filter: from:(allowlisted senders) -> label "Briefing"
  -> fetch: IMAP EXAMINE "Briefing", SINCE yesterday, read-only
  -> code: SENDER ALLOWLIST again (don't trust the label alone), html -> text,
           strip footers/ads/tracking links, cap length per email
  -> code: split into stories (headings / bullets), keep the source + original link
  -> dedupe vs state: message-ids already seen; story fingerprints from the last N days
  -> Gemini (structured JSON): cluster the same story across newsletters, rank,
     write "what happened / why it matters", cite which newsletter(s) carried it
  -> validator: every figure in the prose must appear in the source text (same rule as lessons)
  -> render as a section; fail closed to "no newsletters today" and name any that didn't arrive
```

### Risks to design for up front
- **Prompt injection.** Anyone can email you, and newsletters carry ads. Fence the email text,
  allowlist senders in code, and give the model no tools or actions. The job must have no ability to
  send, delete or label mail.
- **Privacy.** A filter mistake could feed a personal email to Gemini's free tier, which may use the
  input for training. The code-side sender allowlist is the real safeguard. Consider a paid tier
  for this call.
- **Copyright / publishing.** This repo and its Pages site are **public**. Publishing summaries of
  paid newsletters (WSJ especially) on a public URL counts as redistribution. The bigger project
  should serve this section from somewhere private (an authenticated app, or Cloudflare
  Pages + Access), or keep the summaries short with links back to the source.

## 5. Moving into the bigger project: recommended path

1. **Don't copy the code wholesale.** Start the new project's session by giving it this file plus
   read access to `owen02hall-coder/morning-brief`, and have it propose its own architecture that
   fits the bigger app's stack.
2. **Port the pieces in this order:** market numbers → news RSS → newsletters (new) → audio →
   lessons/policy if still wanted. Each piece gets its own assumption test first.
3. **Keep this repo running** until the new briefing has matched it for a week, then disable
   `briefing.yml` here.
4. **If you do want the history inside the new repo**, `git subtree add --prefix=legacy/morning-brief
   <url> main` brings it in as a reference folder without tying the two together.
