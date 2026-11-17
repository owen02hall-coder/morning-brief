# Build brief: the morning briefing inside Atlas

**For the Claude session working in the Atlas repo.** This document is the full instruction set.
Read it top to bottom before writing any code. The reference implementation is the GitHub repo
`owen02hall-coder/morning-brief` (attach it read-only). Its `documentation/architecture.md`,
`operations.md` and `integrations.md` and `scripts/config.py` hold every URL, parse rule and edge
case mentioned here. **Rebuild fresh in Atlas's own stack; use that repo as a reference, not as code
to copy.**

---

## 1. The goal

Atlas replaces the old morning briefing **completely**, and adds one new section: a summary of the
finance newsletters that arrive in the owner's Gmail. Nothing in the old app is "for later". The old
app keeps running until Atlas has matched it for a week; then its `briefing.yml` workflow is
disabled.

**Ready by 6:30am America/Denver, every day.** Private: only the owner can see it, because it
summarizes paid newsletters.

## 2. What the briefing contains (full scope)

| Section | Source | Key needed |
|---|---|---|
| Markets: S&P 500, Nasdaq Composite, 10-year Treasury, VIX (close, change, plain-English why) | Yahoo Finance chart API | none |
| 30-year mortgage rate | Freddie Mac PMMS CSV (weekly) | none |
| Watchlist: RSI-14 + position in 1-month closing band → one action, buy / trim / hold | Yahoo Finance, 6 months of daily closes; ticker list the owner can edit | none |
| Market breadth: % of S&P 500 and Nasdaq-100 above 200-day average, alerts below 40% and 30% | TradingView scanner ∩ Wikipedia member lists | none |
| World news | RSS: BBC World, Al Jazeera, Guardian World, NPR World | none |
| Across the country (what happened and what it means, never the partisan fight) | RSS: AP, NPR National | none |
| Emerging tech | RSS: Ars Technica, The Verge, MIT Technology Review, Hacker News | none |
| Health and science (findings, not science-funding politics) | RSS: BBC Health, NPR Science, NPR Health | none |
| Business news (feeds the market "why") | RSS: MarketWatch, Yahoo Finance, CNBC | none |
| Policy that affects the owner | Federal Register API (6 agencies, 45-day window) + Utah Legislature passed-bills page + static yearly calendar | none |
| **Newsletters (new)** | Gmail label "Briefing", via a read-only Apps Script relay (§5) | Gemini |
| Owen's Alphabet Soup: one lesson a day, Quick / Medium / Long | Gemini proposes article titles → Wikipedia action API fetches the article → Gemini writes from it → code validates against it | Gemini |
| Audio of the whole briefing, then the lesson | Gemini TTS | Gemini |

Exact feed URLs: `scripts/config.py` (`WORLD_FEEDS`, `US_FEEDS`, `TECH_FEEDS`, `SCIENCE_FEEDS`,
`BUSINESS_FEEDS`, `FR_API`, `UTAH_BASE_URL`, `POLICY_CALENDAR`, `WIKI_API`).

## 3. Length setting (every section)

The owner chooses **Ultra-short / Short / Medium** as a saved setting.

- **Ultra-short:** 3–4 sentences, ending with a one-line bottom line.
- **Short (default):** one line per theme, plus a bottom line.
- **Medium:** 1–2 sentences per theme, with named companies and key figures. General background goes
  on its own line labeled **Context**. When sources disagree on a figure, show both, attributed;
  never pick one.

Rules:
- Generate all three lengths in **one** model call, as three fields of the structured output, so
  they can't contradict each other. Run the same validator on all three.
- Narrate only the chosen length, so audio isn't paid for three times.
- Group stories by theme (pharma, energy, banks, data centers, distressed…), not one bullet per item.
- Every fact cites its source (e.g. `ES`, `SS`). "Why" explanations are labeled background, never
  presented as reported.
- Tone: simple and professional. No emojis.

**Reference design:** a hand-built sample of the newsletter section at all three lengths, from the
2026-11-17 issues: https://claude.ai/artifact/LjoQQReJzXBnd35c7KyUXj

## 4. Where it runs (agreed design)

- **Job:** a Vercel function in Atlas, `/api/briefing`. Writes to Neon in its own table
  (`briefing_docs`), not `hub_docs`, so newsletter text stays out of `/api/data`, the 30-second page
  refresh and the Google Sheet relay snapshot.
- **Trigger:** an Apps Script timer at about **5:30am Denver**, one retry at **6:00**. A date gate
  makes repeat calls no-ops. Vercel's daily cron is only a backup.
- **Shown:** the Morning briefing button next to the date on Today, with Read and Speak, served by
  the same passcode-protected API as the rest of Atlas.
- **Time limit:** a Vercel Hobby function stops at 300 seconds. The old app's run takes about
  7 minutes, mostly lesson audio paced 20 seconds apart for the free tier. Split the work (for
  example, lesson audio in a separate invocation) or confirm the billed key removes the pacing.
  **Resolve this in the proposal before building.**
- **Audio:** if the mp3 is too large for a function response, store it separately behind a private
  link instead of serving it inline.

## 5. Newsletters

### Senders

| Newsletter | Sender | Arrives (Denver) |
|---|---|---|
| Short Squeez | `press@shortsqueez.co` | ~2:30am weekdays |
| Exec Sum | `news@execsum.co` | ~4:00am weekdays, not on market holidays |
| WSJ morning newsletter | not yet received | — |
| Dealhook | not yet received | — |

`news@execsum.co` also sends login codes ("… is your login code"). Skip those. Add WSJ and Dealhook
only after a first real issue arrives, and move the run time later if either arrives after 5:30.

### Reading mail

- A separate Apps Script ("Atlas Briefing Mail") reads the **Briefing** label and posts the text to
  Atlas with a token that can only add briefing mail. The job that calls the model holds no mail
  access at all.
- The script must use the **Advanced Gmail Service** with `gmail.readonly` declared in
  `appsscript.json`. `GmailApp` may request full mail access. **The test that proves a delete is
  refused runs before the owner authorizes anything.**
- Check the sender in code (and DKIM where available). Don't trust the label alone.

### Processing

```
relay posts email → code: sender allowlist, skip login codes, HTML → text
  → code: drop sponsor and filler sections by heading ("Together with", "Presented by",
          "A Message from", memes, book pick, events, referral blurbs, merch)
  → code: split into stories, keep source + link
  → dedupe: message IDs already seen; story fingerprints from recent days
  → Gemini (structured JSON, 3 lengths): merge the same story across newsletters, group by theme,
     cite sources
  → validator: every number must appear in the source email; flag implausible figures
  → page: name any newsletter not received today
```

### What the first real issues showed (2026-11-17)

1. **Merging works.** Seven stories appeared in both newsletters; each should show once, citing both.
2. **Sources disagree.** J&J/Ollin: "up to $3.33B" (ES) vs "$2.2B" (SS). Both pass a
   number-in-source check. Show both, attributed.
3. **A number in the source can still be wrong.** ES printed a "$6.6B seed round" (almost certainly
   $6.6M). Add a plausibility check (e.g. seed round over $1B is flagged), or leave small items out.
4. **About half of each issue is ads or filler.** Sponsor blocks can read like editorial (e.g. the
   Mizuho "message"), so cut by section heading, not by how it reads.
5. **Links are tracking redirects.** Resolve them or link to the issue itself.

## 6. Principles (keep these; they took the longest to learn)

1. **Numbers come from data, never from the model.** Code computes every figure and passes it in as
   a fact. The model explains.
2. **Validate model prose against its source.** Reject prose with a $, %, or year missing from the
   source text (the Alphabet Soup lesson also rejects anything shaped like a drug dosage).
3. **Fail closed per item, and name the gap.** A dead source drops that item and says so on the
   page. Never show a stale or invented value. One bad source never kills the day.
4. **Never skip a day.** Model down: use the fallback model. Both down: ship raw numbers and
   headlines.
5. **Fence all third-party text** (news, policy, articles, **email**) between BEGIN/END markers and
   tell the model it is data, not instructions. The job has no tools and no ability to send, delete
   or change mail.
6. **Separate choosing from writing.** The lesson flow: the model names an article, code fetches it,
   the model writes from the fetched text. Newsletters: code splits stories, the model merges and
   summarizes.
7. **One implementation per classification.** Page and audio read the same published field (e.g.
   the watchlist action), so they can't disagree.
8. **"Ready" only after publishing.** The ready notification fires only after the new edition is
   saved, so it never points at yesterday's page. Audio carries its date, so old audio can't attach
   to a new page.
9. **Alphabet Soup progress lives with the reader.** A new lesson comes up only when the reader
   finishes the briefing audio or taps "New lesson". An unfinished lesson is still there tomorrow.
   Domains rotate evenly: money, home/car repair, health and emergencies, judgement and persuasion.

## 7. Traps already hit (don't repeat them)

- Scheduled jobs run late at the top of the hour. Use odd minutes and dedupe by date.
- State fields that were declared but never written shipped twice. Use one writer per state key.
- A guard nobody triggers isn't a guard. One test sat dead for 22 days. Every check needs a schedule.
- Gemini free tier limits per minute as well as per day. Space TTS calls, set a deadline inside the
  time limit.
- Gemini preview models get retired. Keep a fallback model chain and test every model in it weekly.
- Don't hold a push or write credential while parsing untrusted text when you can avoid it.

## 8. Build order

1. Markets (+ mortgage)
2. News sections (world, country, tech, health and science, business)
3. Newsletters
4. Audio
5. Alphabet Soup
6. Policy
7. Watchlist and breadth

**Each source gets an assumption test before code depends on it**, run from Vercel (not a dev
sandbox) and re-run weekly:

| Source | Test |
|---|---|
| Yahoo | Four symbols return two settled closes; a bad symbol fails closed |
| RSS | Each feed parses with title, link and date inside the window |
| Gemini text | Returns valid JSON in all three lengths; a planted fake figure is rejected |
| Mail relay | Can read the label; a delete attempt is refused |
| Newsletters | Real issues pass the sender check; a login-code email is skipped; sponsor blocks are cut; one story in two fixtures merges and cites both; an email saying "ignore your instructions" changes nothing |
| Audio | Returns in time, fits the size limit, plays on iPhone |
| Wikipedia | A real title returns article text; a disambiguation page or stub is rejected |
| Federal Register / Utah | A known window returns results; zero results is treated as broken, not quiet |
| TradingView + member lists | Enough members match; too few fails closed |

## 9. What the owner provides

- **Gemini key, billed, in a new Google Cloud project with a budget cap.** The old app keeps its own
  free key. Put it in Vercel → central-hub → Settings → Environment Variables as `GEMINI_API_KEY`.
- **`BRIEFING_INGEST_TOKEN`** and **`CRON_SECRET`**: random 32+ character strings, same place.
- **Apps Script:** the session supplies the script; the owner pastes it, adds
  `BRIEFING_INGEST_TOKEN` under Script properties, and authorizes once, *after* the read-only test
  passes.
- **Gmail filter:** from `news@execsum.co OR press@shortsqueez.co` → label `Briefing`, never spam,
  category Primary.

Never ask for passwords or keys in chat. Say where to put them.

## 10. How to work

- Work on a branch and open a pull request. Another session pushes to `main`.
- **Before building, reply with an updated proposal** covering the full scope above, the 300-second
  limit, and anything that doesn't fit Atlas. Wait for "go".
