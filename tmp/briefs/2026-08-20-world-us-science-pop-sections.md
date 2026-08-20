# Brief: new briefing sections — US national news, health/science/disasters, and a light pop-culture touch

## Why

The reader asked for "big news stories that don't necessarily have to do with economics, just the
world — things to be aware of," plus "a pop culture thing, short and sweet… I want to be in touch
slightly."

The first half of that request turned out to be **already built**. A review of the last seven
archived editions shows `world` is doing exactly the job described — Indonesia's 7.7 earthquake,
Israeli airstrikes, Ukraine drone strikes, China/Taiwan blockade reporting, a Polish pilgrim bus
crash, France's aid-in-dying law, Imran Khan moved to hospital. Only a minority of items skewed
economic. So the felt gap is NOT "world news is missing"; it is three narrower things:

1. **US national news has no home at all.** `summarize.SYSTEM` says: "World news: only globally
   significant events, **not granular or partisan US politics**." That rule exists to keep partisan
   noise out, and it works — but it also means a Supreme Court ruling, a hurricane landfall, a
   recall, or a major federal action reaches the reader nowhere. The policy section only covers
   rules that affect him *personally*; world only covers the globally significant.
2. **Health / science / disasters** are uncovered as a category.
3. **World is capped at 3 items** and he simply wants more of it.

Pop culture is genuinely new — there is no entertainment feed in the project today.

## Context

- `scripts/data/news.py` — `_bucket(feeds)` is source-agnostic and already does per-feed isolation,
  a 72h window (`NEWS_WINDOW_HOURS`), title-normalized dedupe, and a per-bucket cap. **A new section
  is a new dict in config plus a bucket call — the fetch layer needs no new machinery.**
- `get_news()` returns `{world, business, tech, available}`; `available` drives
  `data_availability`, and the docstring notes "world news must always ship; treat empty world as
  unavailable." New buckets must decide their own availability semantics — a silent pop-culture day
  is normal, and must NOT be reported as degraded the way an empty world bucket is.
- `scripts/config.py` — `WORLD_FEEDS` / `BUSINESS_FEEDS` / `TECH_FEEDS`, `MAX_WORLD_ITEMS = 3`,
  `MAX_TECH_ITEMS = 3`, `MAX_CANDIDATES_PER_BUCKET = 25`.
- `scripts/summarize.py` — `Narrative` (pydantic) drives a structured-output call; new sections mean
  new schema fields, new prompt lines, `_articles_block` bucket list, and `_allowed_urls` (the
  citation allowlist — **a URL not in it is dropped by `_validate_items`**, so a new bucket that is
  not added there will silently produce zero items).
- `scripts/tts.py` `compose_script()` and `docs/app.js` `speechText()` are hand-mirrored narrations,
  now guarded by `scripts/briefing-assumptions/12-narration-mirror.py` (byte equality across
  Python and Node). **Any new section must land in both or CI fails** — this is by design.
- `tts._dedupe_across()` / `app.js dedupeAcross()` already drop a story filed in two buckets
  (content-word Jaccard >= 0.6, or identical URL). It generalizes to N buckets as-is.
- `docs/sw.js` `CACHE` must be bumped whenever `docs/app.js` changes, or `shell-guard.yml` fails
  the push and installed PWAs never receive the update.
- Audio is ~3 min today (1.16 MB @ 48 kbps mono) after the 2026-08-20 rates addition.

### Feed probe (all 17 candidates fetched live, 2026-08-20 — every one returned dated entries)

Liveness was never the discriminator; **content shape** was. Sample top items at probe time:

| Feed | Top item at probe | Verdict |
|---|---|---|
| AP Top News | "Alfalfa sprouts linked to food poisoning illnesses" | **USE** — event-based |
| NPR National | "What we know about the Penn State cocaine trafficking…" | **USE** — event-based |
| CBS US | "Woman accused of plotting 'major attack' on New York" | maybe — crime-heavy |
| Guardian US | "Melania Trump appears to nod to questions about absence" | **REJECT** — political gossip |
| NPR Science | "Former Fauci adviser Dr. David Morens pleads guilty" | weak — that is legal news |
| BBC Sci/Env | "My family have fished this river for 300 years" | weak — feature writing |
| Guardian Science | "It's finally raining, but the drought's not over" | weak — feature writing |
| NASA | "SmallSat 2026" | **REJECT** — press releases |
| ScienceDaily | "Schizophrenia's lost brain connections follow a surprising…" | research churn, not awareness |
| Variety | "Prime Video Unveils Landmark $2 Billion-Plus Investment" | **REJECT** — trade/industry news |
| Hollywood Reporter | "Dave Bautista Officially Cast as Kratos in God of War" | maybe — casting is water-cooler |
| NPR Pop Culture | "As the Tupac murder trial continues…" | **USE** — actual cultural conversation |
| BBC Entertainment | "BBC DJ Trevor Nelson reveals brain tumour surgery" | **USE** — but UK-skewed |
| ESPN Top | "Projecting next year's QB market" | preview/analysis |
| ESPN NBA | "Thunder offseason recap and early-season preview" | preview/analysis |
| CBS Sports | "Raiders vs. Texans prediction, odds, start time" | betting lines |
| Guardian Sport | "Premier League returns and Arsenal sense opportunity" | preview/analysis |

**The sports finding is the important one: not one of the four sports feeds was serving a RESULT.**
Sports RSS is organised around anticipation — previews, projections, odds. The reader asked for
"only genuinely huge results," which is close to the opposite of what these feeds emit.

## Decisions

- **Do NOT add a second "world" section.** World already delivers the requested content; a parallel
  section would duplicate it and fight the cross-bucket dedupe added the same day. Instead raise
  `MAX_WORLD_ITEMS` 3 -> 4.
- **Add a US national news section**, fed by **AP Top News + NPR National only.** Guardian US is
  rejected on evidence (see table) and CBS US held in reserve as crime-heavy.
- **Govern it with an events-not-contest rule**, since the existing blanket exclusion of US politics
  is being relaxed: report *events and outcomes* (a ruling came down, a bill passed, a storm made
  landfall, an agency acted) and never the *contest* about them (who is winning, what each side
  said, polling, "critics slammed"). Chosen because it is mechanically checkable rather than a
  matter of taste — a gate can assert the absence of contest-framing vocabulary.
- **Frame the third section as health / science / disasters, sourced from general news desks
  (AP / NPR / BBC), not from research feeds.** Probe evidence: science feeds return journal findings
  and feature writing, while the "things to be aware of" the reader means — an earthquake, an
  outbreak — arrive through general news. Sourcing this from ScienceDaily/NASA would deliver
  abstracts and press releases.
- **Pop culture: NPR Pop Culture + BBC Entertainment.** Variety and Hollywood Reporter are trade
  publications; the reader explicitly chose "what people are talking about" over industry news.
- **Pop culture length: one line, 1-2 items**, no source read aloud, placed last before the sign-off.
- **Sports: Utah teams (Jazz, BYU, Utah) plus genuinely huge results from anywhere.** Synthesised
  from two selections that need reconciling: Utah teams get the lower bar (a notable result), while
  everything else must be genuinely huge (a final, a title, a record). **Requires a "something
  concluded" filter, and will be legitimately silent most days** — that silence is correct
  behaviour, not a broken section, and must not be reported as degraded.
- **Audio is selective; the page is full.** All new sections render fully on the page. The audio
  reads US + health/science normally but takes only the TOP item from pop/sports. Keeps the
  drive-time cut near 4 minutes without reducing what is captured.
- **Fold in the must-knows dedupe.** `tldr` already restates the world stories nearly verbatim;
  adding three sections compounds that. Extend the existing `_dedupe_across` treatment so the
  must-knows are not re-read by the sections beneath them — narration only, page unchanged.

## Rejected Alternatives

- **A new "world news" section** — rejected as duplication; the existing bucket already does it, as
  seven days of archives show.
- **Guardian US / Variety / NASA / ScienceDaily as sources** — rejected on probed content shape, not
  on availability. All four are alive; all four emit the wrong kind of item.
- **Reading everything in the audio (~5-6 min)** — rejected in favour of a selective narration. Note
  this is the one decision that puts page and audio out of step; see below.
- **Dropping sports entirely** — offered and declined; the reader wants Utah teams.
- **Making the rates "why" paragraphs page-only to buy back length** — offered and not taken; the
  reader kept them after asking for them the same day.

## Where Reasoning Clashed

**Selective audio vs. page/audio parity.** Every prior decision in this project has pushed page and
audio toward saying the same thing — that is the entire premise of `12-narration-mirror.py`, and the
device-voice fallback exists so a listener never gets a *different* briefing. Deciding that the audio
reads only the top pop/sports item deliberately breaks that symmetry for the first time.

The case for it: the audio is a drive-time cut with a hard attention budget, the page has none, and
the reader explicitly wants pop culture to stay tiny. The case against: "page and audio differ" is
exactly the class of drift the mirror gate was built to prevent, and a future maintainer reading the
gate will find a documented exception that the gate itself cannot distinguish from a bug. A
reasonable person could argue the sections should simply be short enough in both places, keeping one
narration and one truth.

Not resolved by fiat: **the mirror gate must be extended to treat the selective-narration rule as
part of the contract** (both implementations must select the same top item), rather than the rule
living only in a comment.

## One Thing to Do First

Add the US national news section end to end — `US_FEEDS` (AP + NPR National) in config, a `us` bucket
in `news.get_news()`, a `us` field on the `Narrative` schema with the events-not-contest rule in the
prompt, the bucket registered in `_articles_block` **and `_allowed_urls`**, rendering in
`docs/app.js`, and the section in both narrations. It is the largest of the three, exercises every
layer a new section touches, and proves the events-not-contest rule against live wire copy before
that rule is depended on twice more.

## Direction

Treat this as one new-section pattern applied three times rather than three bespoke features: config
feeds -> `news._bucket` -> `Narrative` schema + prompt -> allowlist -> page render -> both
narrations -> mirror gate. World stays as-is but widens to 4 items. US national news carries a
mechanically checkable editorial rule because it is re-admitting a category the project deliberately
excluded. Health/science/disasters comes from general news desks, not research feeds. Pop culture
and sports stay deliberately tiny, are allowed to be silent, and the audio reads only their top item.
