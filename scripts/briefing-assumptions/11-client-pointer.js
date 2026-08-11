#!/usr/bin/env node
/**
 * ASSUMPTION 11 (the lesson pointer advances ONLY when the briefing was actually finished):
 * Owen's Alphabet Soup is the one feature in this project whose core rule is enforced entirely in
 * the browser. The build cannot pick a lesson of the day, because whether the audio reached the end
 * is a fact only the device holds — so docs/app.js's `soup` object IS the feature, and a refactor
 * that fired completion on a pause, a length change, or a cancelled speech queue would silently
 * burn lessons the reader never heard. Nothing on the server side could ever detect that.
 *
 * This file runs docs/app.js against a minimal DOM in Node — no browser, no network, no key.
 *
 *   (C1) The section renders LAST, and shows the oldest unfinished lesson.
 *   (C2) The queue chains today's briefing mp3 -> the chosen tiers' clips -> the shared outro.
 *   (C3) The length setting changes both what is shown and what is queued, and persists.
 *   (C4) Reaching the end of the queue advances the pointer and records a COMPLETION.
 *   (C5) The "New lesson" button advances it too, but records a SKIP — the two must stay
 *        distinguishable, or "did he listen" stops meaning anything.
 *   (C6) A lesson whose clips are missing (a failed TTS day, or audio pruned off the retention
 *        window) falls back to the device voice rather than to silence.
 *   (C7) A reader who has finished the whole deck is told so, instead of the narration handing off
 *        into nothing.
 *   (C8) The history survives a reload.
 *
 * Read-only. Exit: 0 PASS / 1 FAIL / 2 REFUSED.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const GATE = "BRIEFING_SMOKE_ALLOW_DEV";
if (process.env[GATE] !== "true") {
  console.error(`REFUSED: set ${GATE}=true to run assumption tests`);
  process.exit(2);
}

const APP_PATH = path.join(__dirname, "..", "..", "docs", "app.js");
const APP = fs.readFileSync(APP_PATH, "utf8");

// ---------------------------------------------------------------- a DOM, cut to what app.js uses
function mkNode(tag) {
  return {
    tagName: (tag || "").toUpperCase(), children: [], _text: "", className: "", dataset: {},
    style: {}, attrs: {}, onclick: null, disabled: false, type: "",
    currentTime: 0, duration: 0, paused: true,
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    insertBefore(c) { this.children.unshift(c); return c; },
    replaceChild(fresh, old) {
      const i = this.children.indexOf(old);
      if (i >= 0) this.children[i] = fresh; else this.children.push(fresh);
    },
    removeAttribute() {}, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {},
    classList: { add() {}, remove() {}, contains: () => false },
    getBoundingClientRect: () => ({ left: 0, width: 100 }),
    play() { this.paused = false; if (this.onplay) this.onplay(); return Promise.resolve(); },
    pause() { if (!this.paused) { this.paused = true; if (this.onpause) this.onpause(); } },
    load() {},
    querySelector(sel) {
      const [t, cls] = sel.split(".");
      const hit = (n) => (!t || n.tagName === t.toUpperCase()) &&
                         (!cls || (n.className || "").split(" ").includes(cls));
      const walk = (n) => {
        for (const c of n.children) { if (hit(c)) return c; const d = walk(c); if (d) return d; }
        return null;
      };
      return walk(this);
    },
    get textContent() { return this._text; },
    set textContent(v) { this._text = v; this.children = []; },
  };
}
const byId = {};
["updated", "stale", "edition", "briefing", "listen", "listen-btn", "listen-label", "listen-track",
 "listen-fill", "listen-time", "listen-audio", "archive-list", "archive-view", "archive-search",
 "ios-hint", "loading"].forEach((id) => { byId[id] = mkNode("div"); });

global.document = {
  createElement: mkNode,
  createElementNS: (ns, t) => mkNode(t),
  getElementById: (id) => byId[id] || null,
  addEventListener() {},
  visibilityState: "visible",
};
const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};
// defineProperty, not assignment: Node ships a getter-only `globalThis.navigator`, and a plain
// assignment throws here under "use strict" (it fails silently without it — which would leave the
// real navigator in place and quietly change what this test is exercising).
Object.defineProperty(global, "navigator", {
  value: { userAgent: "node", standalone: false }, configurable: true, writable: true,
});
// No speechSynthesis on purpose: the queue must be provably correct without it, and C6/C7 assert on
// the TEXT the device would speak rather than on the speaking.
global.window = { navigator: global.navigator };
global.MediaMetadata = class {};
global.Audio = class { set src(v) { this._src = v; } get src() { return this._src; } };

// ---------------------------------------------------------------- fixtures
const BRIEFING = {
  generated_at: new Date().toISOString(), date: "2026-08-11",
  tldr: ["A thing happened."], market: { sp500: { value: 100, change: 1 }, ndx: null, why: "" },
  yield_10y: null, vix: null, breadth: {}, policy: [], policy_upcoming: [], policy_calendar: [],
  tech: [], world: [], weekly_recap: null, data_availability: {},
};
const lesson = (id, withAudio) => ({
  id, date: "2026-08-11", domain: "Money mechanics", title: `Lesson ${id}`, hook: "Hook.",
  quick: "Quick body.", more: "More body.", deep: "Deep body.", takeaway: "Do the thing.",
  source: { title: "Credit score", url: "https://en.wikipedia.org/wiki/Credit_score" },
  audio: withAudio
    ? { quick: `lessons/${id}-quick.mp3`, more: `lessons/${id}-more.mp3`, deep: `lessons/${id}-deep.mp3` }
    : {},
});
const DECK = { lessons: [lesson("a", true), lesson("b", true), lesson("c", false)],
               outro: "lessons/outro.mp3" };
global.fetch = async (url) => {
  const body = url.startsWith("briefing.json") ? BRIEFING
    : url.startsWith("lessons.json") ? DECK
    : url.startsWith("briefing-audio.json") ? { date: BRIEFING.date }
    : url.startsWith("archive/index.json") ? []
    : null;
  if (body === null) throw new Error("404 " + url);
  return { ok: true, json: async () => body };
};

const mod = { exports: {} };
new Function("module", APP + "\nmodule.exports = { soup, player };")(mod);
const { soup, player } = mod.exports;

// ---------------------------------------------------------------- checks
let fails = 0;
const check = (name, ok, detail) => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
  if (!ok) fails++;
};
const section = () => byId["briefing"].querySelector("section.soup");
const shownTitle = () => {
  const t = section() && section().querySelector("h3.soup-title");
  return t ? t.textContent : null;
};
const saved = () => JSON.parse(store["soup.v1"] || "{}");

(async () => {
  await new Promise((r) => setTimeout(r, 60));   // let main()'s async load settle

  console.log("\nC1  renders last, showing the oldest unfinished lesson");
  const classes = byId["briefing"].children.map((c) => c.className);
  check("the soup section is last on the page", classes[classes.length - 1] === "soup",
    classes.join(" | "));
  check("shows the oldest unfinished lesson", shownTitle() === "Lesson a", String(shownTitle()));

  console.log("\nC2  the queue chains briefing -> lesson clips -> outro");
  check("medium queues briefing + 2 tiers + outro", player.clips.length === 4,
    player.clips.map((c) => c.src).join(" -> "));
  check("no spoken tail when every clip exists", player.tail === "");
  check("the queue knows which lesson it would complete", player.lessonId === "a");

  console.log("\nC3  the length setting changes what plays, and persists");
  const lengths = section().querySelector("div.soup-lengths");
  const press = (label) => lengths.children.find((b) => b.textContent === label).onclick();
  press("Long");
  check("long queues 3 tiers", player.clips.length === 5, String(player.clips.length));
  press("Quick");
  check("quick queues 1 tier", player.clips.length === 3, String(player.clips.length));
  check("the choice persisted", saved().length === "quick");

  console.log("\nC4  finishing the queue is what advances the pointer");
  check("still on the same lesson before finishing", shownTitle() === "Lesson a");
  player.finish();
  check("advanced to the next lesson", shownTitle() === "Lesson b", String(shownTitle()));
  check("recorded as COMPLETED, not skipped",
    saved().completed.join() === "a" && saved().skipped.length === 0);
  check("the queue now points at the next lesson", player.lessonId === "b");

  console.log("\nC5  the button advances too, but records a skip");
  section().querySelector("button.soup-next").onclick();
  check("advanced again", shownTitle() === "Lesson c", String(shownTitle()));
  check("recorded as SKIPPED, not completed",
    saved().skipped.join() === "b" && saved().completed.join() === "a");

  console.log("\nC6  a lesson with no clips falls back to the device voice, not to silence");
  check("only the briefing clip is queued", player.clips.length === 1,
    player.clips.map((c) => c.src).join());
  check("the lesson's own prose is what gets spoken", player.tail.includes("Lesson c"),
    player.tail.slice(0, 60));

  console.log("\nC7  the end of the deck is stated, not left dangling");
  player.finish();
  const msg = section().querySelector("p.muted");
  check("the page says so", !!msg && msg.textContent.includes("caught up"));
  check("the audio says so too", player.tail.includes("caught up"), player.tail);
  check("nothing is left to complete", player.lessonId === null);

  console.log("\nC8  the history survives a reload");
  soup.prefs = { length: "medium", completed: [], skipped: [] };
  soup.load();
  check("length, completions and skips all reload",
    soup.prefs.length === "quick" && soup.prefs.completed.join() === "a,c" &&
    soup.prefs.skipped.join() === "b", JSON.stringify(soup.prefs));

  console.log(fails ? `\nFAIL: ${fails} check(s)` : "\nPASS: the client pointer behaves");
  process.exit(fails ? 1 : 0);
})();
