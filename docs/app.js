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

function breadthSection() {
  // Static tap-through links to the StockCharts Bullish Percent Index pages. The on-screen
  // computed value is a planned follow-up; for now the links give direct access.
  const sec = el("section");
  sec.appendChild(el("h2", null, "Market breadth"));
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

function render(b, into) {
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
  market.appendChild(grid);
  if (b.market && b.market.why) market.appendChild(el("p", "why", b.market.why));
  into.appendChild(market);

  into.appendChild(breadthSection());

  into.appendChild(itemList("Emerging tech", b.tech));
  into.appendChild(itemList("World", b.world));

  if (b.weekly_recap) {
    const sec = el("section", "recap");
    sec.appendChild(el("h2", null, "Weekly recap"));
    const card = el("div", "card");
    card.appendChild(el("p", null, b.weekly_recap));
    sec.appendChild(card);
    into.appendChild(sec);
  }
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
    render(b, document.getElementById("briefing"));
  }
  showFreshness(b);
}

async function main() {
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
