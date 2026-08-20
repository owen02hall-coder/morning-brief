"""Audio edition: compose a spoken narration of the briefing and synthesize it with Gemini TTS.

Free-tier friendly. The narration is composed deterministically in code (no extra LLM text call)
from the already-built briefing dict, so the audio can never contradict the page.

Output contract (the briefing): writes a ready-to-publish MP3 (mono, 48 kbps, encoded in-process
via lameenc — the GitHub runner image has no ffmpeg) to config.AUDIO_MP3_PATH. The workflow moves
it to docs/briefing-audio.mp3 + writes docs/briefing-audio.json ({"date": ...}) ONLY when the file
exists — the client shows the player only when the manifest date matches the briefing date, so a
failed/skipped audio day falls back to the on-device voice, never to stale audio.

Output contract (Owen's Alphabet Soup): `generate_lesson_audio()` writes THREE clips per lesson
straight into docs/lessons/, one per depth tier, plus a one-off `outro.mp3` reused forever. Three
clips instead of one file is what makes the reader's quick/medium/long setting possible without
synthesizing the lesson three times: the client plays [1], [1,2] or [1,2,3] back to back. There is
no manifest to keep honest because the deck entry only ever claims the clips that actually wrote.

Everything here is non-fatal by design: no audio must never kill the briefing.
"""
import os
import re
import time
from datetime import date, datetime

from . import config


def _spoken_pct(change, value):
    """Day-over-day percent (vs previous close), spoken sign included. None when unknowable.

    A move that rounds to 0.0% is spoken as "essentially unchanged" rather than "up 0.0 percent",
    for the same reason the index moves below collapse to "flat" — the VIX trades in hundredths, so
    a real 0.03% move would otherwise be read aloud as a zero that still claims a direction."""
    if change is None:
        return None
    prev = (value or 0) - change
    if not prev:
        return None
    pct = (change / prev) * 100
    if abs(pct) < 0.05:
        return "essentially unchanged"
    direction = "up" if change >= 0 else "down"
    return f"{direction} {abs(pct):.1f} percent"


def _spoken_bps(change):
    """A rate move in basis points, spoken. None when the move itself is unknown.

    Basis points rather than "point zero five percent": the page already speaks this number in bps
    (docs/app.js numberCard, mode "bps") and a yield move read as a percent of a percent is the
    single most misheard figure in a rates readout."""
    if change is None:
        return None
    bps = round(change * 100)
    if bps == 0:
        return "essentially unchanged"
    return f"{'up' if bps > 0 else 'down'} {abs(bps)} basis points"


def _spoken_day(iso, with_year=False):
    """'2026-08-13' -> 'August 13' (or 'January 1, 2027'). None if it will not parse.

    `with_year` is on for POLICY effective dates and off for a market as-of: a rule that bites in a
    different calendar year is a different fact from one that bites this month, and "January 1"
    alone would let the listener assume the nearer one."""
    try:
        fmt = "%B %d, %Y" if with_year else "%B %d"
        return datetime.strptime(iso, "%Y-%m-%d").strftime(fmt).replace(" 0", " ")
    except (TypeError, ValueError):
        return None


# --- Cross-bucket repeats -------------------------------------------------------------------------
#
# The model fills `tech` and `world` from overlapping article pools, so one story (an export ban on
# chips, a state-backed cyber incident) legitimately lands in both. On the PAGE that is two cards the
# reader's eye skips in a second; in the AUDIO it is the same paragraph read twice with no way to
# skip past it. Deduped here and in docs/app.js speechText ONLY — the page keeps both cards, because
# this is a listening problem, not a data problem.

_STORY_OVERLAP = 0.6      # Jaccard overlap of content words above which two items are one story.
                          # Deliberately high: dropping a genuinely distinct item is the worse
                          # error, since the listener has no way to discover what went missing.
_STOPWORDS = frozenset(
    "a an the and or but of to in on for with at by from as is are was were be been being it its "
    "this that these those has have had will would can could new after over into out up down more "
    "than then they them their there here about also said says".split())


def _key_words(text):
    """Content words of one item's summary, for the overlap test. Lowercased, punctuation dropped,
    stopwords and 1-2 letter tokens removed so the comparison is about subject matter."""
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOPWORDS}


def _same_story(a, b):
    """True when two narration items are the same story. Mirror of docs/app.js sameStory().

    An identical URL is decisive on its own. Otherwise it is content-word overlap, which is what
    catches the same event filed by two different outlets under two different headlines."""
    if a.get("url") and a.get("url") == b.get("url"):
        return True
    wa, wb = _key_words(a.get("summary")), _key_words(b.get("summary"))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= _STORY_OVERLAP


# The must-knows are read FIRST and are a compression of the very stories the sections below then
# read again. Measured over 10 archived editions (162 must-know/item pairs), and the measurement is
# why this uses a different metric from _same_story: a bullet is a SUBSET of the item it summarises,
# so Jaccard is depressed by the length gap and misses obvious repeats. "Civilian deaths in Ukraine
# reached their highest..." against its near-identical bullet scored 0.46 Jaccard; the Indonesia
# earthquake pair scored 0.26. Containment — the shared words as a fraction of the SHORTER text —
# scored those same pairs 0.85 and 0.60.
#
# Every pair down to 0.45 containment that was read by hand was genuinely the same story (Unitree,
# Panama Canal fees, Apple/Alibaba), so 0.5 sits just below the confirmed true positives with a
# margin. Erring slightly toward suppression is the right bias here because this affects the AUDIO
# ONLY — the page still renders every item, so an over-suppressed story is one the reader can still
# see, while an under-suppressed one is a paragraph they must sit through twice with no skip button.
_TLDR_CONTAINMENT = 0.5


def _covered_by_tldr(item, tldr_words):
    """True when this item is a story the must-knows already told. `tldr_words` is a list of word
    sets, prepared once by the caller rather than per item."""
    wi = _key_words(item.get("summary"))
    if not wi:
        return False
    for wt in tldr_words:
        if wt and len(wi & wt) / min(len(wi), len(wt)) >= _TLDR_CONTAINMENT:
            return True
    return False


def _dedupe_across(buckets, tldr_words=()):
    """`buckets` is [(label, items)] in SPOKEN order; returns the same shape with any item that
    repeats an earlier bucket's story removed. First occurrence wins, so tech keeps the story and
    world drops it — tech is narrated first, and reordering the sections to change that would be a
    bigger surprise than which section a shared story ends up filed under."""
    kept, out = [], []
    for label, items in buckets:
        fresh = []
        for it in items or []:
            if _covered_by_tldr(it, tldr_words):
                continue
            if any(_same_story(it, prev) for prev in kept):
                continue
            fresh.append(it)
            kept.append(it)
        out.append((label, fresh))
    return out


# --- The rates readout ----------------------------------------------------------------------------

def _rate_lines(briefing):
    """The 10-year, the 30-year mortgage and the VIX — each read as a level, then its move, then the
    reason the page already gives for it, and finally the overall market 'why'.

    The mortgage rate carries its release date out loud. PMMS is a WEEKLY survey, so on four mornings
    out of five this number is several days old; saying "as of August 13" is the difference between a
    figure the listener can act on and one they will assume is this morning's."""
    out = []

    y = briefing.get("yield_10y")
    if y and y.get("value") is not None:
        move = _spoken_bps(y.get("change"))
        out.append(f"The 10-year Treasury yield is {y['value']} percent"
                   + (f", {move}." if move else "."))
        if y.get("why"):
            out.append(y["why"])

    mg = briefing.get("mortgage")
    if mg and mg.get("value") is not None:
        move = _spoken_bps(mg.get("change"))
        day = _spoken_day(mg.get("asof"))
        line = f"The 30-year fixed mortgage is {mg['value']} percent"
        if move:
            line += f", {move} in Freddie Mac's weekly survey"
        if day:
            line += f", as of {day}"
        out.append(line + ".")
        if mg.get("why"):
            out.append(mg["why"])

    v = briefing.get("vix")
    if v and v.get("value") is not None:
        move = _spoken_pct(v.get("change"), v.get("value"))
        out.append(f"The VIX is {v['value']}" + (f", {move}." if move else "."))
        if v.get("why"):
            out.append(v["why"])

    market_why = (briefing.get("market") or {}).get("why")
    if market_why:
        out.append(market_why)
    return out


# --- The weekly policy digest ---------------------------------------------------------------------

def _policy_lines(briefing, weekday):
    """Read the policy section ALOUD ONCE A WEEK (config.POLICY_AUDIO_WEEKDAY), covering the whole
    week rather than only the day it happens to be read on.

    `policy_week` is the rolling record built by state.record_policy. Today's briefing only ever
    holds today's finds, so reading `policy` here would silently drop everything found on the other
    six days — the exact opposite of what a weekly digest is for.

    Returns [] on every other weekday, and a positive "nothing landed" line on a quiet week: a
    section that simply vanishes is indistinguishable from a section that broke."""
    if weekday != config.POLICY_AUDIO_WEEKDAY:
        return []

    week = (briefing.get("policy_week") or [])[:config.MAX_POLICY_SPOKEN]
    out = ["This week, in policy that affects you."]

    def describe(it):
        parts = [p for p in ((it.get("what_happened") or "").strip(),
                             (it.get("effect") or "").strip()) if p]
        if not parts:
            return None
        when = _spoken_day(it.get("effective_date"), with_year=True)
        return " ".join(parts) + (f" That takes effect {when}." if when else "")

    spoken = [d for d in (describe(i) for i in week) if d]
    if spoken:
        out.extend(spoken)
    else:
        out.append("No new rules or bills landed for you this week.")

    # "What's coming" minus anything already read out above, so a rule found this week is not
    # described twice in one sitting — the same repeat the tech/world dedupe exists to stop.
    seen = {i.get("url") for i in week if i.get("url")}
    ahead = [i for i in (briefing.get("policy_upcoming") or [])
             if i.get("url") not in seen][:config.MAX_POLICY_SPOKEN]
    ahead_lines = [d for d in (describe(i) for i in ahead) if d]
    if ahead_lines:
        out.append("Still ahead of you.")
        out.extend(ahead_lines)
    return out


def compose_script(briefing, has_lesson=False):
    """Deterministic narration. Mirror any change here in docs/app.js speechText().

    Shape, in spoken order: the must-knows, the S&P/Nasdaq percent moves, then the rates readout
    (10-year, 30-year mortgage, VIX — each followed by the reason the page gives for it, then the
    overall market 'why'), the weekly policy digest on config.POLICY_AUDIO_WEEKDAY only, tech,
    world, and the Sunday recap.

    This was a leaner cut until 2026-08-20 — indices only, no rates, no whys. The reader asked for
    the three rate figures and the reasoning behind them, so the audio now carries them. Breadth is
    still page-only, and the page still shows strictly more than the audio says.

    Tech and world are deduped against each other: one story filed in both buckets is read ONCE.

    `has_lesson` swaps the sign-off for a hand-off into Owen's Alphabet Soup, which is a SEPARATE
    audio file the client queues immediately after this one. The build cannot bake the lesson into
    this mp3: which lesson is current is a fact only the phone holds (it advances only when the
    audio actually finished), so the build can know that a lesson EXISTS and nothing more. If the
    client turns out to have none queued it says so in the device voice — see docs/app.js."""
    parts = []
    d = None
    try:
        d = date.fromisoformat(briefing.get("date", ""))
    except ValueError:
        pass
    day = d.strftime("%A, %B %d").replace(" 0", " ") if d else "today"
    parts.append(f"Good morning. This is your briefing for {day}.")

    tldr = briefing.get("tldr") or []
    if tldr:
        parts.append("The must-knows.")
        for i, t in enumerate(tldr, 1):
            parts.append(f"{i}. {t}")

    m = briefing.get("market") or {}
    moves = []
    for name, n in (("S and P 500", m.get("sp500")), ("Nasdaq", m.get("ndx"))):
        if n and n.get("change") is not None:
            prev = n["value"] - n["change"]
            pct_val = (n["change"] / prev) * 100 if prev else None
            if pct_val is None:
                continue
            if abs(pct_val) < 0.05:   # "up 0.0 percent" reads silly — call it flat
                moves.append(f"the {name} is flat")
            else:
                moves.append(f"the {name} is {'up' if pct_val >= 0 else 'down'} {abs(pct_val):.1f} percent")
    if moves:
        parts.append("Markets: " + ", and ".join(moves) + ".")

    parts.extend(_rate_lines(briefing))
    # weekday() comes off the briefing's OWN date, never the clock: a --force rebuild of Monday's
    # edition late on Tuesday must still be Monday's edition, digest and all.
    parts.extend(_policy_lines(briefing, d.weekday() if d else None))

    # Order is spoken order, and _dedupe_across resolves a shared story to whichever bucket comes
    # FIRST here. US before world is deliberate: a story that is both a US event and globally
    # significant (a hurricane, a federal action with worldwide reach) is more useful framed as the
    # thing that happened at home.
    for label, items in _dedupe_across([("In tech", briefing.get("tech")),
                                        ("Across the country", briefing.get("us")),
                                        ("Around the world", briefing.get("world"))],
                                       tldr_words=[_key_words(t) for t in tldr]):
        if items:
            parts.append(f"{label}.")
            for it in items:
                s = (it.get("summary") or "").strip()
                src = (it.get("source") or "").strip()
                if s:
                    parts.append(f"{s} That's from {src}." if src else s)

    if briefing.get("weekly_recap"):
        parts.append("Your weekly recap.")
        parts.append(briefing["weekly_recap"])

    parts.append("And now, Owen's Alphabet Soup." if has_lesson
                 else "That's your briefing. Have a great day.")
    text = " ".join(p if re.search(r"[.!?]$", p) else p + "." for p in parts)
    return re.sub(r"https?://\S+", "", text)   # URLs are unreadable noise if any slip through


# --- Lesson narration ---------------------------------------------------------------------------

# Spoken once at the end of whichever depth the reader chose, so it lives in its own clip generated
# ONCE and reused forever. Baking a closing line into each tier would mean three closings per lesson
# (or a lesson that just stops), and re-synthesizing a fixed sentence every day would spend a free-
# tier request on an identical result.
OUTRO_TEXT = "That's your alphabet soup. Have a great day."
OUTRO_FILENAME = "outro.mp3"


def compose_lesson_segments(lesson):
    """The three cumulative clips, in play order. Mirror any change in docs/app.js soupSpeech()."""
    # No "and now, the soup" opener here: the briefing narration already hands off (compose_script's
    # has_lesson branch), and this clip also plays on its own when the reader is catching up on an
    # older lesson. Announcing it twice is the more likely mistake, so it is announced once, there.
    return [
        ("quick", f"{lesson['title']}. {lesson['hook']} {lesson['quick']} {lesson['takeaway']}"),
        ("more", lesson["more"]),
        ("deep", lesson["deep"]),
    ]


# --- Synthesis ----------------------------------------------------------------------------------

_last_call = [0.0]   # monotonic timestamp of the last TTS request (process-global, see _pace)


def _pace():
    """Keep at least LESSON_TTS_MIN_INTERVAL seconds between TTS requests.

    This feature took the daily TTS count from 1 to 4, and the free tier is limited per MINUTE as
    well as per day. Four requests fired back to back would trip the per-minute limit and lose the
    lesson audio on a working day — a silent, recurring failure, which is this project's bar for
    spending code on a guard. Generation itself usually takes longer than the interval, so in
    practice this sleeps rarely; it exists for the case where it does not."""
    wait = config.LESSON_TTS_MIN_INTERVAL - (time.monotonic() - _last_call[0])
    if _last_call[0] and wait > 0:
        print(f"tts: pacing — waiting {wait:.0f}s before the next request")
        time.sleep(wait)
    _last_call[0] = time.monotonic()


# Transient TTS failures, by the shape the Gemini SDK reports them in.
#
# Deliberately NOT scripts/data/retry.py. That module classifies `urllib` exceptions and spends a
# per-run budget sized for the ~12 HTTP fetches of the policy + PMMS legs; the SDK raises its own
# error types (which `transient_reason` fails closed on, so it would never retry at all), and the
# limit being worked around here is the free tier's per-MINUTE quota, not a flaky third-party host.
# Two different budgets protecting two different things, kept separate on purpose.
_TTS_TRANSIENT_CODES = frozenset({408, 429, 500, 502, 503, 504})
_TTS_TRANSIENT_TEXT = ("resource_exhausted", "unavailable", "deadline", "timeout", "internal",
                       "rate limit", "overloaded", "too many requests")


def _tts_transient(exc):
    """A short reason string when `exc` looks retryable, else None.

    None is the fail-closed answer, matching scripts/data/retry.py's rule: a malformed request or a
    revoked key must fail immediately rather than burn three slow attempts proving it.

    The SDK surfaces the status as `.code` on its own error classes; the text scan is the backstop
    for transport errors raised by the underlying HTTP stack, which carry no code at all."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return f"HTTP {code}" if code in _TTS_TRANSIENT_CODES else None
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return type(exc).__name__
    blob = f"{type(exc).__name__}: {exc}".lower()
    for needle in _TTS_TRANSIENT_TEXT:
        if needle in blob:
            return needle
    return None


def _synthesize(text, style):
    """One TTS request, retried on TRANSIENT failures. Returns (pcm, sample_rate), or RAISES.

    The retry is the load-bearing part, not a nicety. Before it existed a single 429 lost a lesson
    tier PERMANENTLY: generate_lesson_audio() only ever ran for the entries created that morning, so
    nothing ever revisited the gap, and the reader met the phone's own voice on that lesson for as
    long as it sat at the head of their deck. 2026-08-13 shipped with no `quick` clip and 2026-08-14
    with no `more` for exactly this reason. `backfill_lesson_audio()` repairs the ones already on
    disk; this is what stops new ones being created.

    It never returns None: an empty payload is retried like a transport failure and then raised,
    because a 200 carrying no audio is the other way a tier used to go missing silently. Callers
    therefore have no None branch to write — they already wrap this in the try/except that keeps
    audio non-fatal, and that is where a permanent error or a spent attempt budget lands."""
    from google import genai
    from google.genai import types

    attempts = max(1, int(config.TTS_RETRY_ATTEMPTS) + 1)
    for attempt in range(1, attempts + 1):
        _pace()
        try:
            # Same client-side timeout rationale as summarize.py: an unbounded hang here would eat
            # the 10-minute job budget that the publish leg still needs.
            client = genai.Client(http_options=types.HttpOptions(timeout=180_000))
            resp = client.models.generate_content(
                model=config.TTS_MODEL,
                contents=style + text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=config.TTS_VOICE))),
                ),
            )
            part = resp.candidates[0].content.parts[0]
            pcm = part.inline_data.data
            if not pcm or len(pcm) < 1000:
                # A 200 carrying no audio. Retried like a transport failure rather than accepted:
                # an empty payload is the other way a tier used to go missing silently.
                raise ValueError("empty/tiny audio payload")
            mime = part.inline_data.mime_type or ""
            m = re.search(r"rate=(\d+)", mime)
            return pcm, (int(m.group(1)) if m else 24000)
        except Exception as e:
            reason = "empty payload" if isinstance(e, ValueError) else _tts_transient(e)
            if reason is None or attempt >= attempts:
                raise
            delay = config.TTS_RETRY_BACKOFF * attempt
            print(f"tts: {reason} on attempt {attempt}/{attempts} ({type(e).__name__}: {e}); "
                  f"retrying in {delay}s")
            time.sleep(delay)


def _write_mp3(pcm, rate, path=None, bit_rate=48):
    import lameenc
    enc = lameenc.Encoder()
    enc.set_bit_rate(bit_rate)    # mono speech: transparent enough, ~1.3 MB for ~4 min
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(5)
    mp3 = bytes(enc.encode(pcm)) + bytes(enc.flush())
    path = path or config.AUDIO_MP3_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(mp3)
    os.replace(tmp, path)   # atomic: never leave a half-written mp3 behind
    return len(mp3)


def generate(briefing, has_lesson=False):
    """Synthesize the briefing narration to AUDIO_MP3_PATH. Returns True on success, False otherwise.

    Never raises to the caller's happy path — audio is an enhancement; the page and the push
    must ship regardless.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        print("tts: GEMINI_API_KEY not set — skipping audio")
        return False
    try:
        out = _synthesize(compose_script(briefing, has_lesson=has_lesson),
                          "Read this morning news briefing aloud in a warm, clear, unhurried "
                          "news-anchor voice: ")
        size = _write_mp3(*out)
        print(f"tts: wrote {size} bytes mp3 to {config.AUDIO_MP3_PATH} "
              f"({config.TTS_MODEL}/{config.TTS_VOICE})")
        return True
    except Exception as e:
        print(f"tts: audio generation failed (non-fatal): {e}")
        return False


def ensure_outro():
    """Synthesize the shared closing clip if it is not already on disk. Returns its published path
    (relative to the PWA root) or None. Costs one request once, then never again."""
    path = os.path.join(config.LESSON_AUDIO_DIR, OUTRO_FILENAME)
    rel = f"lessons/{OUTRO_FILENAME}"
    if os.path.exists(path):
        return rel
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        out = _synthesize(OUTRO_TEXT, "Read this warmly and unhurried, as a sign-off: ")
        _write_mp3(*out, path=path, bit_rate=48)
        print(f"tts: wrote the reusable lesson outro to {path}")
        return rel
    except Exception as e:
        print(f"tts: outro generation failed (non-fatal): {e}")
        return None


def generate_lesson_audio(lesson, deadline=None):
    """Synthesize the three depth clips for one lesson into docs/lessons/.

    Returns {tier: published_path} for the clips that actually wrote — possibly empty, possibly
    partial. The caller stores exactly that on the deck entry, so the client can tell what is
    playable; a tier whose clip is missing is read by the phone's own voice instead. Partial is
    handled rather than treated as failure because the tiers are independent files and a lost third
    clip should not cost the reader the first two.

    `deadline` is a `time.monotonic()` value past which no further requests are made. The lesson leg
    runs inside briefing.yml's `timeout-minutes: 10`, and a cancelled job ships NO briefing at all —
    strictly worse than a lesson that has to be read aloud by the device. Never raises.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        print("tts: GEMINI_API_KEY not set — skipping lesson audio")
        return {}
    out = {}
    for tier, text in compose_lesson_segments(lesson):
        if deadline is not None and time.monotonic() > deadline:
            print(f"tts: out of time budget — skipping the '{tier}' clip and any after it")
            break
        path = os.path.join(config.LESSON_AUDIO_DIR, f"{lesson['id']}-{tier}.mp3")
        try:
            got = _synthesize(text, "Read this short explanatory lesson aloud in a warm, clear, "
                                    "unhurried voice, as if explaining it to a friend on a drive: ")
            size = _write_mp3(*got, path=path, bit_rate=48)
            out[tier] = f"lessons/{lesson['id']}-{tier}.mp3"
            print(f"tts: wrote {size} bytes for lesson clip '{tier}'")
        except Exception as e:
            print(f"tts: lesson clip '{tier}' failed (non-fatal): {e}")
    return out


def missing_lesson_clips(deck):
    """[(entry, [tier, ...])] for deck entries INSIDE the audio-retention window that are missing a
    clip, oldest lesson first. A pure inspection — no network, no writes.

    "Missing" means the deck does not claim the tier OR it claims a file that is not on disk. Both
    are checked because they fail identically for the listener and arise differently: the first from
    a synthesis error, the second from a half-finished commit or a manual delete.

    Oldest-first is the whole point of the ordering. `docs/app.js soup.current()` serves the OLDEST
    unfinished lesson, so the entry at the head of the reader's deck is the one whose missing clip
    they actually hit — repairing the newest first would fix the one they reach last.

    Only the last LESSON_AUDIO_RETAIN entries are considered: `_prune_lesson_audio()` deletes files
    outside that window and clears their `audio` key, so synthesizing one would be work destroyed
    minutes later in the same run."""
    window = (deck.get("lessons") or [])[-config.LESSON_AUDIO_RETAIN:]
    out = []
    for e in window:
        audio = e.get("audio") or {}
        gaps = []
        for tier, _text in compose_lesson_segments(e):
            rel = audio.get(tier)
            if not rel or not os.path.exists(os.path.join(config.DOCS_DIR, rel)):
                gaps.append(tier)
        if gaps:
            out.append((e, gaps))
    return out


def backfill_lesson_audio(deck, deadline=None, limit=None):
    """Re-synthesize clips that are missing from lessons still inside the retention window.

    Returns the number of clips written. Mutates the `audio` dict on the entries it repairs; the
    caller writes the deck. NEVER raises.

    WHY THIS EXISTS. `generate_lesson_audio()` only ever runs for the entries created that morning,
    so a tier lost to a transient TTS error was lost for good — and because the reader's pointer
    serves the oldest unfinished lesson first, one bad morning parks a device-voice lesson at the
    head of the queue until they skip past it. The retry inside `_synthesize()` stops new gaps
    appearing; this closes the ones already on disk.

    Bounded three ways, because this is repair work competing with today's own clips for a free-tier
    budget and a 10-minute job: `limit` clips per run (config.LESSON_AUDIO_BACKFILL_MAX), the same
    `deadline` the daily lesson leg honours, and the retention window itself."""
    if not os.environ.get("GEMINI_API_KEY"):
        return 0
    limit = config.LESSON_AUDIO_BACKFILL_MAX if limit is None else limit
    written = 0
    try:
        for entry, gaps in missing_lesson_clips(deck):
            segments = dict(compose_lesson_segments(entry))
            for tier in gaps:
                if written >= limit:
                    print(f"tts: backfill stopped at the {limit}-clip cap; "
                          f"the rest are repaired on later runs")
                    return written
                if deadline is not None and time.monotonic() > deadline:
                    print("tts: backfill out of time budget — the rest are repaired on later runs")
                    return written
                text = segments.get(tier)
                if not text:
                    # The deck entry has no prose for this tier, so there is nothing to synthesize
                    # and nothing to repair. Reported rather than skipped in silence: it means the
                    # entry itself is malformed, which no amount of TTS will fix.
                    print(f"tts: backfill cannot repair '{entry.get('id')}' tier '{tier}' — "
                          f"the deck entry carries no text for it")
                    continue
                path = os.path.join(config.LESSON_AUDIO_DIR, f"{entry['id']}-{tier}.mp3")
                try:
                    got = _synthesize(text, "Read this short explanatory lesson aloud in a warm, "
                                            "clear, unhurried voice, as if explaining it to a "
                                            "friend on a drive: ")
                    size = _write_mp3(*got, path=path, bit_rate=48)
                    entry.setdefault("audio", {})[tier] = f"lessons/{entry['id']}-{tier}.mp3"
                    written += 1
                    print(f"tts: backfilled {size} bytes for '{entry['id']}' tier '{tier}'")
                except Exception as e:
                    print(f"tts: backfill of '{entry.get('id')}' tier '{tier}' failed "
                          f"(non-fatal): {type(e).__name__}: {e}")
    except Exception as e:
        print(f"tts: backfill pass failed (non-fatal): {type(e).__name__}: {e}")
    return written
