"""Audio edition: compose a spoken narration of the briefing and synthesize it with Gemini TTS.

Free-tier friendly: exactly ONE TTS request per day. The narration is composed
deterministically in code (no extra LLM text call) from the already-built briefing dict, so the
audio can never contradict the page.

Output contract: writes a ready-to-publish MP3 (mono, 48 kbps, encoded in-process via lameenc —
the GitHub runner image has no ffmpeg) to config.AUDIO_MP3_PATH. The workflow moves it to
docs/briefing-audio.mp3 + writes docs/briefing-audio.json ({"date": ...}) ONLY when the file
exists — the client shows the player only when the manifest date matches the briefing date, so a
failed/skipped audio day falls back to the on-device voice, never to stale audio. Everything here
is non-fatal by design: no audio must never kill the briefing.
"""
import os
import re

from . import config


def _spoken_pct(change, value):
    """Day-over-day percent (vs previous close), spoken sign included."""
    prev = (value or 0) - (change or 0)
    if not prev:
        return None
    pct = (change / prev) * 100
    direction = "up" if change >= 0 else "down"
    return f"{direction} {abs(pct):.1f} percent"


def _index_line(name, n):
    if not n:
        return f"{name} data is unavailable today."
    level = f"{n['value']:,.0f}" if n["value"] >= 100 else f"{n['value']:g}"
    if n.get("change") is None:
        return f"The {name} last closed at {level}."
    pct = _spoken_pct(n["change"], n["value"])
    return f"The {name} closed at {level}, {pct}." if pct else f"The {name} closed at {level}."


def compose_script(briefing):
    """Deterministic narration of the whole briefing, in page order."""
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
    y, v = briefing.get("yield_10y"), briefing.get("vix")
    parts.append("Markets.")
    parts.append(_index_line("S and P 500", m.get("sp500")))
    parts.append(_index_line("Nasdaq", m.get("ndx")))
    if y:
        line = f"The ten-year Treasury yield is {y['value']:g} percent"
        if y.get("change") is not None:
            bps = round(y["change"] * 100)
            line += f", {'up' if bps >= 0 else 'down'} {abs(bps)} basis points"
        parts.append(line + ".")
    if v:
        line = f"The VIX is at {v['value']:g}"
        pct = _spoken_pct(v.get("change"), v["value"]) if v.get("change") is not None else None
        parts.append(line + (f", {pct}." if pct else "."))
    if m.get("why"):
        parts.append(m["why"])
    if y and y.get("why"):
        parts.append(y["why"])
    if v and v.get("why"):
        parts.append(v["why"])

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

    parts.append("That's your briefing. Have a great day.")
    text = " ".join(p if re.search(r"[.!?]$", p) else p + "." for p in parts)
    return re.sub(r"https?://\S+", "", text)   # URLs are unreadable noise if any slip through


def _write_mp3(pcm, rate):
    import lameenc
    enc = lameenc.Encoder()
    enc.set_bit_rate(48)          # mono speech: transparent enough, ~1.3 MB for ~4 min
    enc.set_in_sample_rate(rate)
    enc.set_channels(1)
    enc.set_quality(5)
    mp3 = bytes(enc.encode(pcm)) + bytes(enc.flush())
    tmp = config.AUDIO_MP3_PATH + ".tmp"
    with open(tmp, "wb") as f:
        f.write(mp3)
    os.replace(tmp, config.AUDIO_MP3_PATH)   # atomic: never leave a half-written mp3 behind
    return len(mp3)


def generate(briefing):
    """Synthesize the narration to AUDIO_MP3_PATH. Returns True on success, False otherwise.

    Never raises to the caller's happy path — audio is an enhancement; the page and the push
    must ship regardless.
    """
    if not os.environ.get("GEMINI_API_KEY"):
        print("tts: GEMINI_API_KEY not set — skipping audio")
        return False
    try:
        from google import genai
        from google.genai import types

        script = compose_script(briefing)
        # Same client-side timeout rationale as summarize.py: an unbounded hang here would eat
        # the 10-minute job budget that the publish leg still needs.
        client = genai.Client(http_options=types.HttpOptions(timeout=180_000))
        resp = client.models.generate_content(
            model=config.TTS_MODEL,
            contents=("Read this morning news briefing aloud in a warm, clear, unhurried "
                      "news-anchor voice: " + script),
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
            return False
        mime = part.inline_data.mime_type or ""
        m = re.search(r"rate=(\d+)", mime)
        size = _write_mp3(pcm, int(m.group(1)) if m else 24000)
        print(f"tts: wrote {size} bytes mp3 to {config.AUDIO_MP3_PATH} "
              f"({config.TTS_MODEL}/{config.TTS_VOICE})")
        return True
    except Exception as e:
        print(f"tts: audio generation failed (non-fatal): {e}")
        return False
