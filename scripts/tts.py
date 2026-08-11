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

from . import config


def _spoken_pct(change, value):
    """Day-over-day percent (vs previous close), spoken sign included."""
    prev = (value or 0) - (change or 0)
    if not prev:
        return None
    pct = (change / prev) * 100
    direction = "up" if change >= 0 else "down"
    return f"{direction} {abs(pct):.1f} percent"


def compose_script(briefing, has_lesson=False):
    """Deterministic narration — deliberately LEANER than the page (user preference 2026-07-05):
    must-knows, the S&P/Nasdaq percent moves only (no index levels, no 10-year/VIX/breadth
    readouts, no 'why' paragraphs), then tech and world items. The page still shows everything;
    the audio is the drive-time cut. Mirror any change here in docs/app.js speechText().

    `has_lesson` swaps the sign-off for a hand-off into Owen's Alphabet Soup, which is a SEPARATE
    audio file the client queues immediately after this one. The build cannot bake the lesson into
    this mp3: which lesson is current is a fact only the phone holds (it advances only when the
    audio actually finished), so the build can know that a lesson EXISTS and nothing more. If the
    client turns out to have none queued it says so in the device voice — see docs/app.js."""
    parts = []
    d = None
    try:
        from datetime import date
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

    for bucket, label in (("tech", "In tech"), ("world", "Around the world")):
        items = briefing.get(bucket) or []
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


def _synthesize(text, style):
    """One TTS request. Returns (pcm_bytes, sample_rate), or None if the payload is unusable."""
    from google import genai
    from google.genai import types

    _pace()
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
        print("tts: empty/tiny audio payload — skipping")
        return None
    mime = part.inline_data.mime_type or ""
    m = re.search(r"rate=(\d+)", mime)
    return pcm, (int(m.group(1)) if m else 24000)


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
        if not out:
            return False
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
        if not out:
            return None
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
            if not got:
                continue
            size = _write_mp3(*got, path=path, bit_rate=48)
            out[tier] = f"lessons/{lesson['id']}-{tier}.mp3"
            print(f"tts: wrote {size} bytes for lesson clip '{tier}'")
        except Exception as e:
            print(f"tts: lesson clip '{tier}' failed (non-fatal): {e}")
    return out
