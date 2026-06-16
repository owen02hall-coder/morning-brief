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

function numberCard(title, obj, unit) {
  const card = el("div", "card");
  card.appendChild(el("h3", null, title));
  if (!obj) {
    card.appendChild(el("p", "muted", "Information not available."));
    return card;
  }
  const v = el("p", "figure", `${obj.value}${unit || ""}`);
  const ch = el("span", obj.change >= 0 ? "up" : "down", `  ${fmtChange(obj.change)}${unit || ""}`);
  v.appendChild(ch);
  card.appendChild(v);
  if (obj.why) card.appendChild(el("p", null, obj.why));
  if (obj.asof) card.appendChild(el("p", "muted", `as of ${obj.asof}`));
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
    card.appendChild(el("p", null, it.summary));
    if (it.url) {
      const a = el("a", "readmore", `Read more — ${it.source || "source"}`);
      a.href = it.url;
      a.target = "_blank";
      a.rel = "noopener";
      card.appendChild(a);
    }
    sec.appendChild(card);
  }
  return sec;
}

function render(b, into) {
  into.innerHTML = "";

  if (b.tldr && b.tldr.length) {
    const sec = el("section", "tldr");
    sec.appendChild(el("h2", null, "The 3 must-knows"));
    const ul = el("ul");
    b.tldr.forEach((t) => ul.appendChild(el("li", null, t)));
    sec.appendChild(ul);
    into.appendChild(sec);
  }

  const market = el("section");
  market.appendChild(el("h2", null, "Markets"));
  const grid = el("div", "grid");
  grid.appendChild(numberCard("S&P 500", b.market && b.market.sp500, ""));
  grid.appendChild(numberCard("Nasdaq", b.market && b.market.ndx, ""));
  grid.appendChild(numberCard("10-year Treasury", b.yield_10y, "%"));
  grid.appendChild(numberCard("VIX", b.vix, ""));
  market.appendChild(grid);
  if (b.market && b.market.why) market.appendChild(el("p", "why", b.market.why));
  into.appendChild(market);

  into.appendChild(itemList("Emerging tech", b.tech));
  into.appendChild(itemList("World", b.world));

  if (b.weekly_recap) {
    const sec = el("section");
    sec.appendChild(el("h2", null, "Weekly recap"));
    sec.appendChild(el("p", null, b.weekly_recap));
    into.appendChild(sec);
  }
}

function showFreshness(b) {
  const updated = document.getElementById("updated");
  const stale = document.getElementById("stale");
  if (!b.generated_at) return;
  const when = new Date(b.generated_at);
  updated.textContent = "Last updated " + when.toLocaleString();
  const ageHours = (Date.now() - when.getTime()) / 36e5;
  if (ageHours > STALE_HOURS) {
    stale.textContent = "Could not refresh — showing the last available briefing.";
    stale.classList.remove("hidden");
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
        const a = el("a", "archive-link", `${e.date} — ${(e.tldr && e.tldr[0]) || ""}`);
        a.href = "#";
        a.onclick = async (ev) => {
          ev.preventDefault();
          const b = await (await fetch(`archive/${e.date}.json`, { cache: "no-store" })).json();
          render(b, view);
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

async function main() {
  try {
    const b = await (await fetch("briefing.json", { cache: "no-store" })).json();
    render(b, document.getElementById("briefing"));
    showFreshness(b);
  } catch (e) {
    document.getElementById("briefing").innerHTML =
      "<p class='muted'>No briefing available yet.</p>";
  }
  loadArchive();
  maybeIosHint();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
}

main();
