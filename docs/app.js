"use strict";

const STALE_HOURS = 28;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function fmtChange(n) {
  if (n == null) return "";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n}`;
}

function fmtValue(v) {
  // Thousands separators for index levels (5,567.19); leaves non-numbers untouched.
  return typeof v === "number"
    ? v.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : String(v);
}

function localDate(iso) {
  // "YYYY-MM-DD" parsed as LOCAL date. new Date("2026-07-05") is UTC midnight,
  // which renders as the previous day in Denver — never use it for date-only strings.
  const [y, m, d] = (iso || "").split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d) : null;
}

function safeHref(url) {
  // Citation URLs originate from third-party feeds (via the model). Only web links may become
  // tap-through anchors — never javascript:/data:/anything else a hostile feed could smuggle in.
  return /^https?:\/\//i.test(url || "") ? url : null;
}

function numberCard(title, obj, unit, mode) {
  const card = el("div", "card");
  card.appendChild(el("h3", null, title));
  if (!obj) {
    card.appendChild(el("p", "muted", "Information not available."));
    return card;
  }
  const v = el("p", "figure", `${fmtValue(obj.value)}${unit || ""}`);
  if (obj.change != null) { // change can be null (single settled close) — show the level alone
    let changeText;
    if (mode === "percent") {
      const prev = obj.value - obj.change; // percent is vs the PREVIOUS close
      changeText = prev
        ? `${obj.change >= 0 ? "+" : ""}${((obj.change / prev) * 100).toFixed(1)}%`
        : `${fmtChange(obj.change)}${unit || ""}`; // divide-by-zero guard
    } else if (mode === "bps") {
      changeText = `${obj.change >= 0 ? "+" : ""}${Math.round(obj.change * 100)} bps`;
    } else {
      changeText = `${fmtChange(obj.change)}${unit || ""}`;
    }
    const ch = el("span", `delta ${obj.change >= 0 ? "up" : "down"}`, changeText);
    v.appendChild(ch);
  }
  card.appendChild(v);
  if (obj.why) card.appendChild(el("p", "tile-why", obj.why));
  if (obj.asof) card.appendChild(el("p", "asof", `as of ${obj.asof}`));
  return card;
}

function itemList(title, items) {
  const sec = el("section");
  sec.appendChild(el("h2", null, title));
  if (!items || !items.length) {
    sec.appendChild(el("p", "muted", "Information not available."));
    return sec;
  }
  for (const it of items) {
    const card = el("div", "card");
    if (it.source) card.appendChild(el("p", "kicker", it.source));
    card.appendChild(el("p", "summary", it.summary));
    const href = safeHref(it.url);
    if (href) {
      const a = el("a", "readmore", "Read more");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";
      a.setAttribute("aria-label", `Read more at ${it.source || "source"}`);
      card.appendChild(a);
    }
    sec.appendChild(card);
  }
  return sec;
}

const BREADTH_STATUS_LABEL = { healthy: "Healthy", watch: "Watch", oversold: "Oversold" };

function breadthCard(label, b) {
  if (!b || b.value == null) return null;
  const card = el("div", "card");
  card.appendChild(el("h3", null, label));
  const fig = el("p", "figure", `${b.value}%`);
  fig.appendChild(el("span", `status ${b.status}`, BREADTH_STATUS_LABEL[b.status] || b.status));
  card.appendChild(fig);
  card.appendChild(el("p", "tile-why", "of members above their 200-day average"));
  if (b.asof) {
    card.appendChild(el("p", "asof",
      `as of ${b.asof}${b.stale ? " (cached — today's scan failed)" : ""}`));
  }
  return card;
}

function breadthSection(breadth) {
  // Computed % above 200-day MA per index; the StockCharts BPI links stay beneath (the exact
  // BPI has no free feed). Handles the legacy single-index shape from pre-2026-07-06 archives.
  const sec = el("section");
  sec.appendChild(el("h2", null, "Market breadth"));
  const shaped = breadth && breadth.value != null ? { sp500: breadth } : (breadth || {});
  const cards = [
    breadthCard("S&P 500", shaped.sp500),
    breadthCard("Nasdaq-100", shaped.ndx100),
  ].filter(Boolean);
  if (cards.length) {
    const grid = el("div", "grid");
    cards.forEach((c) => grid.appendChild(c));
    sec.appendChild(grid);
  }
  sec.appendChild(el("p", "muted", "Below ~30 = oversold / bullish-reversal watch."));
  const chips = el("div", "chips");
  [
    ["S&P 500 ($BPSPX)", "https://stockcharts.com/sc3/ui/?s=%24BPSPX"],
    ["Nasdaq-100 ($BPNDX)", "https://stockcharts.com/sc3/ui/?s=%24BPNDX"],
  ].forEach(([label, href]) => {
    const a = el("a", "chip", label);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    chips.appendChild(a);
  });
  sec.appendChild(chips);
  return sec;
}

// Status strings contain spaces ("Final rule"), so `status ${it.status}` would emit two bogus
// classes. Map value -> class, the same way BREADTH_STATUS_LABEL maps value -> label.
const POLICY_STATUS_CLASS = {
  "Final rule": "final",
  "Proposed": "proposed",
  "Signed in Utah": "final",
};

function policyDate(iso, opts) {
  const d = localDate(iso); // date-only strings must be parsed LOCAL, never via new Date(iso)
  return d ? d.toLocaleDateString(undefined, opts) : iso || "";
}

function policyLink(node, url, label) {
  const href = safeHref(url); // third-party citation URLs — web links only
  if (!href) return false;
  node.href = href;
  node.target = "_blank";
  node.rel = "noopener";
  if (label) node.setAttribute("aria-label", label);
  return true;
}

function policyCard(it) {
  const card = el("div", "card");
  const head = el("div", "policy-head"); // NOT .kicker: that uppercases + letter-spaces, which
  const cls = POLICY_STATUS_CLASS[it.status]; // would mangle "Signed in Utah"
  if (it.status) head.appendChild(el("span", cls ? `status ${cls}` : "status", it.status));
  if (it.source) head.appendChild(el("span", "policy-source", it.source));
  if (head.children.length) card.appendChild(head);
  if (it.what_happened) card.appendChild(el("p", "summary", it.what_happened));
  // The effect line is the point of the section — what this does to you, not what was published.
  if (it.effect) card.appendChild(el("p", "policy-effect", it.effect));
  if (it.effective_date) {
    card.appendChild(el("p", "policy-when",
      `Effective ${policyDate(it.effective_date, { month: "long", day: "numeric", year: "numeric" })}`));
  }
  const a = el("a", "readmore", "Read more");
  if (policyLink(a, it.url, `Read more at ${it.source || "the source"}`)) card.appendChild(a);
  return card;
}

function policyUpcomingCard(items) {
  const card = el("div", "card policy-upcoming");
  const ul = el("ul");
  for (const it of items) {
    const li = el("li");
    // The whole row is the tap target when a link exists — a 44px .readmore per row would
    // triple the height of what is meant to be a compact dated list. Anchor only when the URL
    // is safe; otherwise a plain row, never an <a> without an href.
    const href = safeHref(it.url);
    const row = href ? el("a", "policy-row cardlink") : el("div", "policy-row");
    if (href) policyLink(row, it.url, `${it.what_happened || "Upcoming change"} — details`);
    li.appendChild(row);
    row.appendChild(el("span", "policy-date",
      policyDate(it.effective_date, { month: "short", day: "numeric", year: "numeric" })));
    const body = el("div", "policy-row-body");
    if (it.what_happened) body.appendChild(el("p", "policy-row-what", it.what_happened));
    // The carry exists so a deadline stays MEANINGFUL — never reduce it to a bare headline.
    if (it.effect) body.appendChild(el("p", "policy-effect", it.effect));
    row.appendChild(body);
    ul.appendChild(li);
  }
  card.appendChild(ul);
  return card;
}

function policyCalendarCard(entries) {
  // Recurring annual dates with NO announcement behind them (config.POLICY_CALENDAR). They share
  // the "What's coming" heading with policy_upcoming but must never read as the same kind of thing:
  // an upcoming item HAPPENED and carries a published effective date, a calendar entry is only
  // EXPECTED. Hence a separate card, a muted "Expected" marker where the reported rows print a real
  // date, and this lede.
  const card = el("div", "card policy-upcoming policy-calendar");
  card.appendChild(el("p", "policy-calendar-lede",
    "Recurring dates — expected, not announced. Nobody has published these yet."));
  const ul = el("ul");
  for (const e of entries) {
    const li = el("li");
    const href = safeHref(e.url); // hand-written .gov URLs, but the same guard as any other link
    const row = href ? el("a", "policy-row cardlink") : el("div", "policy-row");
    if (href) policyLink(row, e.url, `${e.label || "Expected change"} — official page`);
    li.appendChild(row);
    // The resolved ISO date exists in the JSON ONLY to order this list, and is deliberately NOT
    // rendered: printing "Nov 30" beside "expected late November" would claim a precision no
    // source has published. The timing lives in the label, in the words the source can support.
    row.appendChild(el("span", "policy-date policy-expected", "Expected"));
    const body = el("div", "policy-row-body");
    if (e.label) body.appendChild(el("p", "policy-row-what", e.label));
    if (e.note) body.appendChild(el("p", "policy-calendar-note", e.note));
    row.appendChild(body);
    ul.appendChild(li);
  }
  card.appendChild(ul);
  return card;
}

function policySection(items, upcoming, calendar) {
  // Returns null when there is nothing to show — deliberately NOT itemList(), whose empty state
  // prints "Information not available." Here empty means "nothing qualified", which is not the
  // same claim. The call site MUST guard: appendChild(null) throws mid-render.
  const list = (Array.isArray(items) ? items : []).filter(Boolean);
  const soon = (Array.isArray(upcoming) ? upcoming : []).filter(Boolean);
  // A calendar entry alone is enough to render the section: it is the only forward-looking content
  // the section has 9 months a year, and the whole reason the calendar exists. Render-when-non-empty
  // still holds — the calendar is empty on ~56% of mornings by design (POLICY_CALENDAR_HORIZON_DAYS).
  const cal = (Array.isArray(calendar) ? calendar : []).filter(Boolean);
  if (!list.length && !soon.length && !cal.length) return null;

  const sec = el("section", "policy");
  sec.appendChild(el("h2", null, "Policy that affects you"));
  list.forEach((it) => sec.appendChild(policyCard(it)));
  if (soon.length || cal.length) {
    sec.appendChild(el("h3", "policy-coming", "What's coming"));
    if (soon.length) sec.appendChild(policyUpcomingCard(soon));
    if (cal.length) sec.appendChild(policyCalendarCard(cal));
  }
  return sec;
}

// ---- Owen's Alphabet Soup ---------------------------------------------------------------------
//
// THE POINTER LIVES HERE, AND NOWHERE ELSE. The build publishes an append-only deck
// (lessons.json); this file decides which entry is current, and it advances on exactly two events:
// the audio genuinely reached the end, or the reader tapped "New lesson". Both are facts only this
// device can observe, which is why the server deliberately does not pick a lesson of the day — an
// unfinished lesson has to still be there tomorrow.
//
// Everything is stored under one localStorage key. Losing it (new phone, cleared site data) costs
// the reading history and restarts the deck from its oldest entry — annoying, never broken.

const SOUP_KEY = "soup.v1";
// Cumulative depths: each tier plays/reads on top of the one before, never instead of it.
const SOUP_TIERS = { quick: ["quick"], medium: ["quick", "more"], long: ["quick", "more", "deep"] };
const SOUP_LENGTHS = [["quick", "Quick"], ["medium", "Medium"], ["long", "Long"]];
const SOUP_CAUGHT_UP = "You're caught up on Alphabet Soup. The next one lands tomorrow morning.";
const SOUP_OUTRO_SPOKEN = "That's your alphabet soup. Have a great day.";
const SOUP_HISTORY_MAX = 400;   // ids kept per list; the deck itself is far shorter

const soup = {
  deck: [],
  outro: null,
  prefs: { length: "medium", completed: [], skipped: [] },

  load() {
    try {
      const saved = JSON.parse(localStorage.getItem(SOUP_KEY) || "{}");
      if (SOUP_TIERS[saved.length]) this.prefs.length = saved.length;
      if (Array.isArray(saved.completed)) this.prefs.completed = saved.completed;
      if (Array.isArray(saved.skipped)) this.prefs.skipped = saved.skipped;
    } catch (e) { /* corrupt or unavailable storage — defaults are a working state */ }
  },
  save() {
    try { localStorage.setItem(SOUP_KEY, JSON.stringify(this.prefs)); } catch (e) { /* private mode */ }
  },
  async fetchDeck() {
    try {
      const d = await (await fetch("lessons.json", { cache: "no-store" })).json();
      this.deck = Array.isArray(d.lessons) ? d.lessons.filter((l) => l && l.id) : [];
      this.outro = typeof d.outro === "string" ? d.outro : null;
    } catch (e) {
      this.deck = [];       // offline before the deck was ever cached — the section just hides
      this.outro = null;
    }
  },
  done() { return new Set(this.prefs.completed.concat(this.prefs.skipped)); },
  // Oldest-unfinished first. Lessons are not news — nothing expires — so working forward through
  // the deck means a week away costs nothing, where "newest each day" would silently drop the ones
  // that were never heard.
  current() { const d = this.done(); return this.deck.find((l) => !d.has(l.id)) || null; },
  waiting() { const d = this.done(); return this.deck.filter((l) => !d.has(l.id)).length; },
  tiers() { return SOUP_TIERS[this.prefs.length] || SOUP_TIERS.medium; },
  advance(id, how) {
    if (!id) return;
    const list = how === "completed" ? this.prefs.completed : this.prefs.skipped;
    if (!list.includes(id)) list.push(id);
    if (list.length > SOUP_HISTORY_MAX) list.splice(0, list.length - SOUP_HISTORY_MAX);
    this.save();
  },
};

function soupSpeech(lesson, tiers) {
  // Mirror of scripts/tts.py compose_lesson_segments — used whenever the clips for the chosen
  // depth are not all on the server (a failed TTS day, or a lesson old enough that its audio has
  // been pruned). The prose is in the deck precisely so this fallback is always possible.
  const seg = {
    quick: `${lesson.title}. ${lesson.hook} ${lesson.quick} ${lesson.takeaway}`,
    more: lesson.more,
    deep: lesson.deep,
  };
  return tiers.map((t) => seg[t]).filter(Boolean).join(" ") + " " + SOUP_OUTRO_SPOKEN;
}

function soupControls(lesson, onChange) {
  const wrap = el("div", "soup-controls");
  const lengths = el("div", "soup-lengths");
  lengths.setAttribute("role", "group");
  lengths.setAttribute("aria-label", "Lesson length");
  SOUP_LENGTHS.forEach(([value, label]) => {
    const b = el("button", "soup-length" + (soup.prefs.length === value ? " on" : ""), label);
    b.type = "button";
    b.setAttribute("aria-pressed", soup.prefs.length === value ? "true" : "false");
    b.onclick = () => {
      if (soup.prefs.length === value) return;
      soup.prefs.length = value;
      soup.save();
      onChange();          // re-render + rebuild the playlist: the audio length changed too
    };
    lengths.appendChild(b);
  });
  wrap.appendChild(lengths);

  const next = el("button", "soup-next", "New lesson");
  next.type = "button";
  if (lesson) {
    // The explicit half of "only give me a new one if I listened": this is the manual override,
    // and it records a SKIP, not a completion, so the two are distinguishable later.
    next.onclick = () => { soup.advance(lesson.id, "skipped"); onChange(); };
  } else {
    next.disabled = true;
  }
  wrap.appendChild(next);
  return wrap;
}

function soupSection(onChange) {
  const sec = el("section", "soup");
  sec.appendChild(el("h2", null, "Owen's Alphabet Soup"));
  const lesson = soup.current();
  const card = el("div", "card soup-card");

  if (!lesson) {
    card.appendChild(el("p", "muted", soup.deck.length
      ? SOUP_CAUGHT_UP
      : "The first lesson lands with tomorrow's briefing."));
    sec.appendChild(card);
    sec.appendChild(soupControls(null, onChange));
    return sec;
  }

  if (lesson.domain) card.appendChild(el("p", "kicker", lesson.domain));
  card.appendChild(el("h3", "soup-title", lesson.title));
  card.appendChild(el("p", "soup-hook", lesson.hook));
  card.appendChild(el("p", "soup-body", lesson.quick));
  // The takeaway sits directly after `quick` and not at the very bottom, because that is exactly
  // where the audio says it: `quick` is a complete lesson with its own action line, and the deeper
  // tiers are extensions after it. Page and audio must not disagree about the shape.
  card.appendChild(el("p", "soup-takeaway", lesson.takeaway));
  const extra = soup.tiers().slice(1);
  if (extra.length) {
    card.appendChild(el("p", "soup-deeper", "Going deeper"));
    extra.forEach((t) => { if (lesson[t]) card.appendChild(el("p", "soup-body", lesson[t])); });
  }
  const src = lesson.source || {};
  const href = safeHref(src.url);
  if (href) {
    const a = el("a", "readmore", `Source: ${src.title || "read more"}`);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    card.appendChild(a);
  }
  sec.appendChild(card);
  sec.appendChild(soupControls(lesson, onChange));
  const waiting = soup.waiting();
  if (waiting > 1) sec.appendChild(el("p", "muted soup-count", `${waiting - 1} more waiting.`));
  return sec;
}

function render(b, into, withSoup) {
  into.innerHTML = "";

  if (b.tldr && b.tldr.length) {
    const sec = el("section", "tldr");
    sec.appendChild(el("h2", null, "The 3 must-knows"));
    const card = el("div", "card");
    const ol = el("ol");
    b.tldr.forEach((t) => ol.appendChild(el("li", null, t)));
    card.appendChild(ol);
    sec.appendChild(card);
    into.appendChild(sec);
  }

  const market = el("section");
  market.appendChild(el("h2", null, "Markets"));
  const grid = el("div", "grid");
  grid.appendChild(numberCard("S&P 500", b.market && b.market.sp500, "", "percent"));
  grid.appendChild(numberCard("Nasdaq", b.market && b.market.ndx, "", "percent"));
  grid.appendChild(numberCard("10-year Treasury", b.yield_10y, "%", "bps"));
  grid.appendChild(numberCard("VIX", b.vix, "", "percent"));
  // Weekly PMMS rate — only when present. Archived editions predate the key, and numberCard's
  // null branch would print a 5th "Information not available." tile where none belongs.
  // "bps", the same mode as the 10-year Treasury, because it is the same units problem: the tile
  // reads "6.66%", so a raw "+0.03%" delta beside it is ambiguous — 0.03 percentage points, or
  // 0.03% of the rate? "+3 bps" cannot be misread, it is how rate moves are quoted, and weekly
  // PMMS moves of 0.01-0.10pp land as clean integers instead of two-decimal fractions.
  // change is null on archived editions and whenever no prior row parsed; numberCard omits it.
  if (b.mortgage) grid.appendChild(numberCard("30-year mortgage", b.mortgage, "%", "bps"));
  market.appendChild(grid);
  if (b.market && b.market.why) market.appendChild(el("p", "why", b.market.why));
  into.appendChild(market);

  into.appendChild(breadthSection(b.breadth));

  // Guarded: policySection returns null when nothing qualified, and appendChild(null) throws.
  // A throw here would leave a half-built page with NO error message (loadBriefing has already
  // committed the seq and advanced lastGeneratedAt, so the visibilitychange refetch would skip
  // re-rendering for the rest of the session), and on the archive path it surfaces as a
  // misleading "you may be offline".
  const policy = policySection(b.policy, b.policy_upcoming, b.policy_calendar);
  if (policy) into.appendChild(policy);

  into.appendChild(itemList("Emerging tech", b.tech));
  into.appendChild(itemList("Across the country", b.us));
  into.appendChild(itemList("World", b.world));

  if (b.weekly_recap) {
    const sec = el("section", "recap");
    sec.appendChild(el("h2", null, "Weekly recap"));
    const card = el("div", "card");
    card.appendChild(el("p", null, b.weekly_recap));
    sec.appendChild(card);
    into.appendChild(sec);
  }

  // Alphabet Soup goes LAST, after everything the briefing had to say — and only on the live page.
  // An archived edition is a record of one day's news; the lesson the reader had not reached yet
  // was never part of that day, and rendering it there would also give two live pointers into the
  // same deck.
  if (withSoup) refreshSoup(into);
}

function refreshSoup(into) {
  const fresh = soupSection(() => refreshSoup(into));
  const existing = into.querySelector("section.soup");
  if (existing) into.replaceChild(fresh, existing);
  else into.appendChild(fresh);
  // The current lesson or the chosen depth just changed, so the queued audio is wrong. Replanning
  // here is what keeps the button and the player from disagreeing about what is about to play.
  player.replan();
}

function showFreshness(b) {
  const updated = document.getElementById("updated");
  const stale = document.getElementById("stale");
  // Masthead edition line shows the BRIEFING's date (not today's) — it must never claim
  // an edition that isn't actually on screen.
  const edition = document.getElementById("edition");
  const ed = localDate(b.date);
  if (edition && ed) {
    edition.textContent = ed.toLocaleDateString(undefined,
      { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }
  if (!b.generated_at) return;
  const when = new Date(b.generated_at);
  updated.textContent = "Updated " + when.toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const ageHours = (Date.now() - when.getTime()) / 36e5;
  if (ageHours > STALE_HOURS) {
    stale.textContent = "Could not refresh — showing the last available briefing.";
    stale.classList.remove("hidden");
  } else {
    stale.classList.add("hidden"); // a resume-refetch may replace a stale copy with a fresh one
  }
}

// ---- Listen: daily audio edition with on-device speech fallback -----------------------------

const ICON_PLAY = "M8 5v14l11-7z";
const ICON_PAUSE = "M6 5h4v14H6zM14 5h4v14h-4z";

function icon(d) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", d);
  svg.appendChild(path);
  return svg;
}

function fmtTime(s) {
  if (!isFinite(s)) return "";
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

// ---- Narration mirror -------------------------------------------------------------------------
//
// Everything from here to speechText() is a line-for-line mirror of scripts/tts.py. It is used
// whenever there is no server-rendered mp3 (a day the build's TTS failed, an archived briefing,
// offline), and the rule the whole feature rests on is that the device voice must say the SAME
// briefing the good voice would have said — otherwise a fallback day silently becomes a different
// product. Change one side, change the other.

const STORY_OVERLAP = 0.6;   // mirror of tts._STORY_OVERLAP
const STOPWORDS = new Set(
  ("a an the and or but of to in on for with at by from as is are was were be been being it its "
   + "this that these those has have had will would can could new after over into out up down more "
   + "than then they them their there here about also said says").split(" "));

function spokenBps(change) {
  // Mirror of tts._spoken_bps. Basis points, because a yield move read as a percent of a percent
  // is the most misheard figure in a rates readout.
  if (change == null) return null;
  const bps = Math.round(change * 100);
  if (bps === 0) return "essentially unchanged";
  return `${bps > 0 ? "up" : "down"} ${Math.abs(bps)} basis points`;
}

const SPOKEN_MONTHS = ["January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"];

function spokenDay(iso, withYear) {
  // Mirror of tts._spoken_day. Built off localDate so a date-only string is never shifted a day by
  // UTC parsing — the same trap safeHref's neighbour documents above.
  const d = localDate(iso);
  if (!d) return null;
  const base = `${SPOKEN_MONTHS[d.getMonth()]} ${d.getDate()}`;
  return withYear ? `${base}, ${d.getFullYear()}` : base;
}

function keyWords(text) {
  // Mirror of tts._key_words.
  const out = new Set();
  for (const w of (text || "").toLowerCase().match(/[a-z0-9]+/g) || []) {
    if (w.length > 2 && !STOPWORDS.has(w)) out.add(w);
  }
  return out;
}

function sameStory(a, b) {
  // Mirror of tts._same_story: identical URL is decisive, otherwise content-word overlap, which is
  // what catches one event filed by two outlets under two headlines.
  if (a.url && a.url === b.url) return true;
  const wa = keyWords(a.summary), wb = keyWords(b.summary);
  if (!wa.size || !wb.size) return false;
  let shared = 0;
  wa.forEach((w) => { if (wb.has(w)) shared += 1; });
  return shared / (wa.size + wb.size - shared) >= STORY_OVERLAP;
}

function dedupeAcross(buckets) {
  // Mirror of tts._dedupe_across. First occurrence wins, so tech keeps a shared story and world
  // drops it — tech is narrated first.
  const kept = [];
  return buckets.map(([label, items]) => {
    const fresh = [];
    (items || []).forEach((it) => {
      if (kept.some((prev) => sameStory(it, prev))) return;
      fresh.push(it);
      kept.push(it);
    });
    return [label, fresh];
  });
}

function rateLines(b) {
  // Mirror of tts._rate_lines: the 10-year, the 30-year mortgage and the VIX, each read as a level,
  // then its move, then the reason the page already gives — then the overall market "why".
  const out = [];
  const y = b.yield_10y;
  if (y && y.value != null) {
    const move = spokenBps(y.change);
    out.push(`The 10-year Treasury yield is ${y.value} percent${move ? ", " + move : ""}.`);
    if (y.why) out.push(y.why);
  }
  const mg = b.mortgage;
  if (mg && mg.value != null) {
    const move = spokenBps(mg.change);
    const day = spokenDay(mg.asof, false);
    // The release date is spoken aloud on purpose: PMMS is a WEEKLY survey, so on most mornings
    // this number is several days old and the listener would otherwise assume it is this morning's.
    let line = `The 30-year fixed mortgage is ${mg.value} percent`;
    if (move) line += `, ${move} in Freddie Mac's weekly survey`;
    if (day) line += `, as of ${day}`;
    out.push(line + ".");
    if (mg.why) out.push(mg.why);
  }
  const v = b.vix;
  if (v && v.value != null) {
    let move = null;
    if (v.change != null) {
      const prev = v.value - v.change;
      if (prev) {
        const pct = (v.change / prev) * 100;
        // Mirror of tts._spoken_pct: a move that rounds to 0.0% must not still claim a direction.
        move = Math.abs(pct) < 0.05 ? "essentially unchanged"
          : `${pct >= 0 ? "up" : "down"} ${Math.abs(pct).toFixed(1)} percent`;
      }
    }
    out.push(`The VIX is ${v.value}${move ? ", " + move : ""}.`);
    if (v.why) out.push(v.why);
  }
  if (b.market && b.market.why) out.push(b.market.why);
  return out;
}

const POLICY_AUDIO_WEEKDAY = 1;   // mirror of config.POLICY_AUDIO_WEEKDAY (Monday). NOTE the
                                  // different convention: Python's date.weekday() is Mon=0, but
                                  // JavaScript's Date.getDay() is Sun=0, so Monday is 1 here and 0
                                  // there. Same day, two numbering schemes — do not "fix" one to
                                  // match the other.
const MAX_POLICY_SPOKEN = 6;      // mirror of config.MAX_POLICY_SPOKEN

function policyLines(b, d) {
  // Mirror of tts._policy_lines. Reads the policy section aloud ONCE A WEEK, covering the whole
  // week via b.policy_week (the build's projection of the rolling state record) rather than just
  // the day it is read on.
  if (!d || d.getDay() !== POLICY_AUDIO_WEEKDAY) return [];
  const week = (b.policy_week || []).slice(0, MAX_POLICY_SPOKEN);
  const out = ["This week, in policy that affects you."];
  const describe = (it) => {
    const parts = [(it.what_happened || "").trim(), (it.effect || "").trim()].filter(Boolean);
    if (!parts.length) return null;
    const when = spokenDay(it.effective_date, true);
    return parts.join(" ") + (when ? ` That takes effect ${when}.` : "");
  };
  const spoken = week.map(describe).filter(Boolean);
  // A positive "nothing landed" line on a quiet week: a section that simply vanishes is
  // indistinguishable from a section that broke.
  if (spoken.length) out.push(...spoken);
  else out.push("No new rules or bills landed for you this week.");

  const seen = new Set(week.map((i) => i.url).filter(Boolean));
  const ahead = (b.policy_upcoming || []).filter((i) => !seen.has(i.url)).slice(0, MAX_POLICY_SPOKEN);
  const aheadLines = ahead.map(describe).filter(Boolean);
  if (aheadLines.length) { out.push("Still ahead of you."); out.push(...aheadLines); }
  return out;
}

function speechText(b, hasLesson) {
  // Mirror of scripts/tts.py compose_script — used when there is no audio file (fallback days,
  // archived briefings, offline). Spoken order: must-knows, the S&P/Nasdaq percent moves, the rates
  // readout (10-year, 30-year mortgage, VIX, each with its "why", then the market "why"), the
  // weekly policy digest on Mondays only, tech, world, the Sunday recap.
  //
  // This was a leaner cut until 2026-08-20 — indices only, no rates, no whys. The reader asked for
  // the three rate figures and the reasoning behind them. Breadth is still page-only.
  //
  // Tech and world are deduped against each other: one story filed in both buckets is read ONCE.
  //
  // `hasLesson` swaps the sign-off for the hand-off into Alphabet Soup, exactly as the server's
  // narration does — the lesson's own text follows immediately after this string.
  const parts = [];
  const d = localDate(b.date);
  parts.push(`Good morning. This is your briefing for ${d
    ? d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }) : "today"}.`);
  (b.tldr || []).forEach((t, i) => parts.push(`${i === 0 ? "The must-knows. " : ""}${i + 1}. ${t}`));
  const moves = [];
  [["S and P 500", b.market && b.market.sp500], ["Nasdaq", b.market && b.market.ndx]]
    .forEach(([name, n]) => {
      if (!n || n.change == null) return;
      const prev = n.value - n.change;
      if (!prev) return;
      const pct = (n.change / prev) * 100;
      moves.push(Math.abs(pct) < 0.05 ? `the ${name} is flat`   // "up 0.0 percent" reads silly
        : `the ${name} is ${pct >= 0 ? "up" : "down"} ${Math.abs(pct).toFixed(1)} percent`);
    });
  if (moves.length) parts.push("Markets: " + moves.join(", and ") + ".");
  parts.push(...rateLines(b));
  // Off the briefing's OWN date, never the clock: an archived Monday edition read on a Thursday is
  // still Monday's edition, digest and all.
  parts.push(...policyLines(b, d));
  // Mirror of tts.compose_script: US before world, so a story that is both resolves to the
  // domestic framing. dedupeAcross keeps the FIRST bucket's copy.
  dedupeAcross([["In tech.", b.tech], ["Across the country.", b.us],
                ["Around the world.", b.world]]).forEach(([label, items]) => {
    if (items.length) parts.push(label);
    items.forEach((it) => {
      if (it.summary) parts.push(it.source ? `${it.summary} That's from ${it.source}.` : it.summary);
    });
  });
  if (b.weekly_recap) parts.push(`Your weekly recap. ${b.weekly_recap}`);
  parts.push(hasLesson ? "And now, Owen's Alphabet Soup."
                       : "That's your briefing. Have a great day.");
  return parts.join(" ").replace(/https?:\/\/\S+/g, "");
}

function speakChunked(text, onDone) {
  // iOS quietly dies on very long utterances — queue sentence-sized chunks instead.
  const chunks = text.match(/[^.!?]+[.!?]+[\s]*/g) || [text];
  const synth = window.speechSynthesis;
  synth.cancel();
  let remaining = chunks.length;
  chunks.forEach((c) => {
    const u = new SpeechSynthesisUtterance(c);
    u.onend = () => { remaining -= 1; if (remaining === 0 && onDone) onDone(); };
    u.onerror = () => { remaining -= 1; if (remaining === 0 && onDone) onDone(); };
    synth.speak(u);
  });
}

function setButton(btn, playing) {
  btn.textContent = "";
  btn.appendChild(icon(playing ? ICON_PAUSE : ICON_PLAY));
  btn.setAttribute("aria-label", playing ? "Pause the audio briefing" : "Play the audio briefing");
}

// The one play button drives a QUEUE, not a file: today's briefing mp3, then the clips for the
// current lesson at the chosen depth, then the shared sign-off. Reaching the end of that queue is
// the signal the whole feature turns on — it is the only honest evidence the briefing was actually
// heard all the way through, and it is the one thing that advances the deck pointer.
//
// The queue can end in SPEECH instead of a clip (`tail`): a day the server's TTS failed, a lesson
// old enough that its audio was pruned, or a reader who is caught up and should be told so. The
// prose is in the deck for exactly this reason, so a missing mp3 degrades the voice, never the
// content.
const player = {
  bar: null, btn: null, label: null, track: null, fill: null, time: null, audio: null,
  briefing: null,
  hasEdition: false,        // today's mp3 exists AND its manifest date matches this edition
  clips: [],                // [{src, label}]
  durations: [],
  idx: 0,
  tail: "",                 // spoken by the device voice after the clips (may be the whole thing)
  tailLabel: "",
  lessonId: null,           // the lesson this queue would complete; null when caught up
  playing: false,
  speaking: false,
  speechSeq: 0,             // guards against a cancelled utterance's onend counting as "finished"

  bind() {
    this.bar = document.getElementById("listen");
    this.btn = document.getElementById("listen-btn");
    this.label = document.getElementById("listen-label");
    this.track = document.getElementById("listen-track");
    this.fill = document.getElementById("listen-fill");
    this.time = document.getElementById("listen-time");
    this.audio = document.getElementById("listen-audio");
    this.audio.onended = () => this.next();
    this.audio.onpause = () => { if (!this.speaking) { this.playing = false; this.paint(); } };
    this.audio.onplay = () => { this.playing = true; this.paint(); };
    this.audio.ontimeupdate = () => this.paint();
    this.audio.onloadedmetadata = () => { this.durations[this.idx] = this.audio.duration; this.paint(); };
    this.track.onclick = (ev) => this.seek(ev);
    this.btn.onclick = () => this.toggle();
  },

  stopAll() {
    // playing=false FIRST, and the generation bump before cancel(): cancelling a speech queue fires
    // every pending utterance's onend, and a stale callback that still believed it was playing
    // would count an interrupted lesson as finished — the one mistake this feature must not make.
    this.playing = false;
    this.speaking = false;
    this.speechSeq += 1;
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    if (this.audio) this.audio.pause();
  },

  // Build the queue from the current briefing + the current lesson. Called on load, and again
  // whenever the pointer or the length setting moves.
  replan() {
    // Both guards are load-bearing. render() -> refreshSoup() -> replan() runs BEFORE setupListen()
    // has bound the DOM nodes on first load, and an unguarded `this.bar.classList` there throws
    // inside render — leaving a half-built page with no error message, the same failure the policy
    // section's appendChild(null) guard exists to prevent. setupListen replans immediately after
    // binding, so bailing here costs nothing.
    if (!this.briefing || !this.bar) return;
    const wasPlaying = this.playing;
    this.stopAll();
    const b = this.briefing;
    const lesson = soup.current();
    const tiers = soup.tiers();
    this.clips = [];
    this.tail = "";
    this.tailLabel = "";
    this.lessonId = lesson ? lesson.id : null;

    if (this.hasEdition) {
      // date param defeats the 10-min HTTP cache
      this.clips.push({ src: `briefing-audio.mp3?d=${b.date}`, label: "Today's briefing" });
    } else {
      this.tail = speechText(b, !!lesson);
      this.tailLabel = "Listen (device voice)";
    }

    if (lesson) {
      const paths = tiers.map((t) => (lesson.audio || {})[t]).filter(Boolean);
      // ALL of the chosen tiers must be present, not some: a queue that plays the first clip and
      // then falls into a different voice mid-lesson is worse than one consistent voice.
      if (this.hasEdition && paths.length === tiers.length) {
        paths.forEach((p, i) => this.clips.push({ src: p, label: "Owen's Alphabet Soup" + (i ? " (cont.)" : "") }));
        if (soup.outro) this.clips.push({ src: soup.outro, label: "Owen's Alphabet Soup" });
      } else {
        this.tail = (this.tail ? this.tail + " " : "") + soupSpeech(lesson, tiers);
        this.tailLabel = this.hasEdition ? "Owen's Alphabet Soup (device voice)" : "Listen (device voice)";
      }
    } else if (this.hasEdition) {
      // The deck is not empty on the server (the narration handed off to the soup), but this reader
      // has finished everything in it. Say so rather than ending on a dangling introduction.
      this.tail = SOUP_CAUGHT_UP;
      this.tailLabel = "Owen's Alphabet Soup";
    }

    const speechOnly = !this.clips.length;
    if (speechOnly && !("speechSynthesis" in window)) { this.bar.classList.add("hidden"); return; }
    this.bar.classList.remove("hidden");
    this.idx = 0;
    this.durations = this.clips.map(() => 0);
    this.measure();
    this.paint();
    if (wasPlaying) this.start();     // a length change mid-drive must not silence the player
  },

  // Preload durations so the bar and the countdown describe the WHOLE queue, not the current file.
  // Throwaway elements: the visible <audio> is busy being the transport.
  measure() {
    this.clips.forEach((c, i) => {
      const probe = new Audio();
      probe.preload = "metadata";
      probe.onloadedmetadata = () => {
        if (isFinite(probe.duration)) { this.durations[i] = probe.duration; this.paint(); }
      };
      probe.src = c.src;
    });
  },

  total() { return this.durations.reduce((a, d) => a + (d || 0), 0); },
  elapsed() {
    let t = 0;
    for (let i = 0; i < this.idx; i++) t += this.durations[i] || 0;
    return t + (this.audio && isFinite(this.audio.currentTime) ? this.audio.currentTime : 0);
  },

  paint() {
    setButton(this.btn, this.playing);
    const known = this.clips.length && this.durations.every((d) => d > 0);
    const cur = this.clips[this.idx];
    this.label.textContent = this.speaking || !cur ? (this.tailLabel || "Listen (device voice)")
                                                   : cur.label;
    if (known && !this.speaking) {
      const total = this.total();
      this.track.classList.remove("hidden");
      this.time.classList.remove("hidden");
      this.fill.style.width = `${Math.min(100, (this.elapsed() / total) * 100)}%`;
      this.time.textContent = fmtTime(Math.max(0, total - this.elapsed()));
    } else {
      this.track.classList.add("hidden");
      this.time.classList.add("hidden");
    }
  },

  toggle() {
    if (this.playing) { this.stopAll(); this.paint(); return; }
    this.primeSpeech();
    this.start();
  },

  // iOS only allows speechSynthesis to start inside a user gesture, and the spoken tail of the
  // queue begins from an `ended` event — a media callback, not a tap. Speaking one silent utterance
  // here, inside the tap that started playback, unlocks the API for the rest of the session. Without
  // it the device-voice fallback is simply silent on iPhone, which is the platform this is built for.
  primeSpeech() {
    if (!this.tail || !("speechSynthesis" in window)) return;
    try { window.speechSynthesis.speak(new SpeechSynthesisUtterance(" ")); } catch (e) { /* ignore */ }
  },

  start() {
    if (this.idx < this.clips.length) {
      this.playing = true;
      this.audio.src = this.clips[this.idx].src;
      this.audio.play().catch(() => { this.playing = false; this.paint(); });
      this.paint();
      this.mediaSession();
    } else if (this.tail) {
      this.speak();
    }
  },

  speak() {
    if (!("speechSynthesis" in window)) { this.finish(); return; }
    this.playing = true;
    this.speaking = true;
    const seq = ++this.speechSeq;
    this.paint();
    speakChunked(this.tail, () => {
      if (seq !== this.speechSeq) return;   // a newer queue (or a stop) owns the player now
      this.speaking = false;
      if (this.playing) this.finish();      // only a queue that ran to its end counts as listened
      else this.paint();
    });
  },

  next() {
    this.idx += 1;
    if (this.idx < this.clips.length) { this.start(); return; }
    if (this.tail) { this.speak(); return; }
    this.finish();
  },

  // The queue ran out with nothing left to play: the briefing WAS heard all the way through.
  finish() {
    this.playing = false;
    this.speaking = false;
    const done = this.lessonId;
    this.idx = 0;
    if (done) {
      soup.advance(done, "completed");
      // Re-renders the section with the next lesson and replans the queue behind it.
      refreshSoup(document.getElementById("briefing"));
    } else {
      this.paint();
    }
  },

  seek(ev) {
    if (this.speaking || !this.clips.length || !this.durations.every((d) => d > 0)) return;
    const r = this.track.getBoundingClientRect();
    let target = ((ev.clientX - r.left) / r.width) * this.total();
    for (let i = 0; i < this.clips.length; i++) {
      const d = this.durations[i];
      if (target <= d || i === this.clips.length - 1) {
        if (i !== this.idx) {
          this.idx = i;
          this.audio.src = this.clips[i].src;
          if (this.playing) this.audio.play().catch(() => {});
        }
        this.audio.currentTime = Math.max(0, Math.min(d - 0.25, target));
        this.paint();
        return;
      }
      target -= d;
    }
  },

  mediaSession() {
    if (!("mediaSession" in navigator)) return;
    const d = localDate(this.briefing.date);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: "Morning Briefing" + (d ? " — " + d.toLocaleDateString(undefined,
        { month: "long", day: "numeric" }) : ""),
      artist: "Morning Briefing",
      artwork: [{ src: "icon-512.png", sizes: "512x512", type: "image/png" }],
    });
    navigator.mediaSession.setActionHandler("play", () => this.start());
    navigator.mediaSession.setActionHandler("pause", () => { this.stopAll(); this.paint(); });
  },
};

async function setupListen(b) {
  if (!player.audio) player.bind();
  player.briefing = b;
  // Prefer the real audio edition; the manifest date must MATCH this briefing — yesterday's
  // mp3 must never play under today's page.
  player.hasEdition = false;
  try {
    const r = await fetch("briefing-audio.json", { cache: "no-store" });
    if (r.ok) player.hasEdition = (await r.json()).date === b.date;
  } catch (e) { /* offline or absent — fall through to speech */ }
  player.replan();
}

async function loadArchive() {
  const list = document.getElementById("archive-list");
  const view = document.getElementById("archive-view");
  const search = document.getElementById("archive-search");
  let entries = [];
  try {
    entries = await (await fetch("archive/index.json", { cache: "no-store" })).json();
  } catch (e) {
    return;
  }
  function draw(filter) {
    list.innerHTML = "";
    const f = (filter || "").toLowerCase();
    entries
      .filter((e) => !f || (e.date + " " + (e.tldr || []).join(" ")).toLowerCase().includes(f))
      .forEach((e) => {
        const li = el("li");
        const a = el("a", "archive-item");
        const d = localDate(e.date);
        a.appendChild(el("span", "archive-date",
          d ? d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
            : e.date));
        a.appendChild(el("span", "archive-snippet", (e.tldr && e.tldr[0]) || ""));
        a.href = "#";
        a.onclick = async (ev) => {
          ev.preventDefault();
          try {
            const b = await (await fetch(`archive/${e.date}.json`, { cache: "no-store" })).json();
            render(b, view);
            // Archived editions have no mp3 — offer the device voice when available.
            if ("speechSynthesis" in window) {
              const chip = el("button", "chip", "Listen to this briefing");
              chip.type = "button";
              chip.onclick = () => {
                if (chip.dataset.speaking === "1") {
                  player.stopAll();
                  chip.dataset.speaking = "0";
                  chip.textContent = "Listen to this briefing";
                } else {
                  player.stopAll();
                  chip.dataset.speaking = "1";
                  chip.textContent = "Stop";
                  // No lesson tail here: an archived edition is a record of that day's news, and
                  // finishing it must never advance the live deck pointer.
                  speakChunked(speechText(b, false), () => {
                    chip.dataset.speaking = "0";
                    chip.textContent = "Listen to this briefing";
                  });
                }
              };
              view.insertBefore(chip, view.firstChild);
            }
          } catch (err) { // offline with no cached copy, or a failed fetch — never fail silently
            view.innerHTML = "";
            view.appendChild(el("p", "muted",
              `Couldn't load the ${e.date} briefing — you may be offline.`));
          }
          view.scrollIntoView({ behavior: "smooth" });
        };
        li.appendChild(a);
        list.appendChild(li);
      });
  }
  draw("");
  search.addEventListener("input", () => draw(search.value));
}

function maybeIosHint() {
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  const standalone = window.navigator.standalone === true;
  if (isIos && !standalone) document.getElementById("ios-hint").classList.remove("hidden");
}

let lastGeneratedAt = null;
let loadSeq = 0;
let committedSeq = 0;

async function loadBriefing() {
  // Resume-refetches can overlap. Invalidate on COMMIT, not on start: an older response may still
  // render if no newer response has committed — a newer request that FAILS must not blank the page.
  const seq = ++loadSeq;
  const b = await (await fetch("briefing.json", { cache: "no-store" })).json();
  if (seq <= committedSeq) return; // a newer response already rendered
  committedSeq = seq;
  if (b.generated_at !== lastGeneratedAt) { // only re-render on a new edition (no scroll jank)
    lastGeneratedAt = b.generated_at;
    // The deck is fetched BEFORE the render: the soup section and the audio queue both need to
    // know the current lesson, and a section that appears a moment later would move the page under
    // a reader who is already scrolling. A failed fetch leaves an empty deck, which renders as
    // "the first lesson lands tomorrow" — never as a broken page.
    await soup.fetchDeck();
    // Before render(), because rendering the soup section replans the queue: without this, a
    // day-change re-render would briefly build a queue against YESTERDAY's briefing date.
    // setupListen re-plans a moment later once it knows whether today's mp3 exists.
    player.briefing = b;
    render(b, document.getElementById("briefing"), true);
    setupListen(b).catch(() => {}); // audio/speech wiring must never break the render path
  }
  showFreshness(b);
}

async function main() {
  soup.load();     // the reader's length setting + which lessons they have already finished
  try {
    await loadBriefing();
  } catch (e) {
    // A stranded initial fetch can reject AFTER a resume-refetch already rendered (background/
    // foreground on a slow network) — only show the placeholder if nothing has committed.
    if (committedSeq === 0) {
      document.getElementById("briefing").innerHTML =
        "<p class='muted'>No briefing available yet.</p>";
    }
  }
  loadArchive();
  maybeIosHint();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  // A standalone PWA resumed from the app switcher never reloads the page — refetch on resume so
  // yesterday's briefing (and a stale freshness banner) can't persist all morning.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") loadBriefing().catch(() => {});
  });
}

main();
