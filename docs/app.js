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

  into.appendChild(breadthSection(b.breadth));

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

function speechText(b) {
  // Mirror of scripts/tts.py compose_script — used when there is no audio file (fallback days,
  // archived briefings, offline). Deliberately LEANER than the page (user preference): must-knows,
  // the S&P/Nasdaq percent moves only (no levels, no 10-year/VIX/breadth, no whys), tech, world.
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
  [["tech", "In tech."], ["world", "Around the world."]].forEach(([k, label]) => {
    const items = b[k] || [];
    if (items.length) parts.push(label);
    items.forEach((it) => {
      if (it.summary) parts.push(it.source ? `${it.summary} That's from ${it.source}.` : it.summary);
    });
  });
  if (b.weekly_recap) parts.push(`Your weekly recap. ${b.weekly_recap}`);
  parts.push("That's your briefing. Have a great day.");
  return parts.join(" ").replace(/https?:\/\/\S+/g, "");
}

const listen = {
  mode: null,           // "audio" | "speech"
  playing: false,
  audio: null,
  stopSpeech() {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  },
  stopAll() {
    this.stopSpeech();
    if (this.audio) this.audio.pause();
    this.playing = false;
  },
};

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

async function setupListen(b) {
  const bar = document.getElementById("listen");
  const btn = document.getElementById("listen-btn");
  const label = document.getElementById("listen-label");
  const track = document.getElementById("listen-track");
  const fill = document.getElementById("listen-fill");
  const time = document.getElementById("listen-time");
  const audio = document.getElementById("listen-audio");
  listen.audio = audio;
  listen.stopAll();
  setButton(btn, false);
  fill.style.width = "0%";

  // Prefer the real audio edition; the manifest date must MATCH this briefing — yesterday's
  // mp3 must never play under today's page.
  let hasAudio = false;
  try {
    const r = await fetch("briefing-audio.json", { cache: "no-store" });
    if (r.ok) hasAudio = (await r.json()).date === b.date;
  } catch (e) { /* offline or absent — fall through to speech */ }

  if (hasAudio) {
    listen.mode = "audio";
    audio.src = `briefing-audio.mp3?d=${b.date}`;   // date param defeats the 10-min HTTP cache
    label.textContent = "Listen to today's briefing";
    track.classList.remove("hidden");
    time.classList.remove("hidden");
    audio.onloadedmetadata = () => { time.textContent = fmtTime(audio.duration); };
    audio.ontimeupdate = () => {
      if (audio.duration) {
        fill.style.width = `${(audio.currentTime / audio.duration) * 100}%`;
        time.textContent = fmtTime(audio.duration - audio.currentTime);
      }
    };
    audio.onended = () => { listen.playing = false; setButton(btn, false); fill.style.width = "0%"; };
    audio.onpause = () => { listen.playing = false; setButton(btn, false); };
    audio.onplay = () => { listen.playing = true; setButton(btn, true); };
    track.onclick = (ev) => {
      if (!audio.duration) return;
      const r = track.getBoundingClientRect();
      audio.currentTime = ((ev.clientX - r.left) / r.width) * audio.duration;
    };
    btn.onclick = () => { listen.playing ? audio.pause() : audio.play().catch(() => {}); };
    if ("mediaSession" in navigator) {
      const d = localDate(b.date);
      navigator.mediaSession.metadata = new MediaMetadata({
        title: "Morning Briefing" + (d ? " — " + d.toLocaleDateString(undefined,
          { month: "long", day: "numeric" }) : ""),
        artist: "Morning Briefing",
        artwork: [{ src: "icon-512.png", sizes: "512x512", type: "image/png" }],
      });
      navigator.mediaSession.setActionHandler("play", () => audio.play().catch(() => {}));
      navigator.mediaSession.setActionHandler("pause", () => audio.pause());
    }
    bar.classList.remove("hidden");
  } else if ("speechSynthesis" in window) {
    listen.mode = "speech";
    audio.removeAttribute("src");
    label.textContent = "Listen (device voice)";
    track.classList.add("hidden");
    time.classList.add("hidden");
    btn.onclick = () => {
      if (listen.playing) {
        listen.stopAll();
        setButton(btn, false);
      } else {
        listen.playing = true;
        setButton(btn, true);
        speakChunked(speechText(b), () => { listen.playing = false; setButton(btn, false); });
      }
    };
    bar.classList.remove("hidden");
  } else {
    bar.classList.add("hidden");
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
            // Archived editions have no mp3 — offer the device voice when available.
            if ("speechSynthesis" in window) {
              const chip = el("button", "chip", "Listen to this briefing");
              chip.type = "button";
              chip.onclick = () => {
                if (chip.dataset.speaking === "1") {
                  listen.stopAll();
                  chip.dataset.speaking = "0";
                  chip.textContent = "Listen to this briefing";
                } else {
                  listen.stopAll();
                  chip.dataset.speaking = "1";
                  chip.textContent = "Stop";
                  speakChunked(speechText(b), () => {
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
    render(b, document.getElementById("briefing"));
    setupListen(b).catch(() => {}); // audio/speech wiring must never break the render path
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
