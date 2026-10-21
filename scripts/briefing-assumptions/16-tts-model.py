"""T1-T3: every configured TTS model still answers, through the production call, in the Kore voice.

WHY THIS TEST EXISTS. The whole audio edition — the daily briefing mp3 AND every lesson clip — ran on
ONE model id, gemini-2.5-flash-preview-tts, with no fallback. On 2026-10-21 Google's deprecations page
listed it for shutdown on 2026-11-17. Nothing here would have said so: the day it died, the build
would have shipped with no audio, the phone would have fallen back to the device voice for the
briefing (and, since 2026-10-21, taught no lessons at all), and the only signal would have been a
low-priority "degraded: audio" push naming no cause. Silent enough, and model ids WILL keep retiring,
so it earns a machine.

The replacement (gemini-3.8-flash-tts) also changed two behaviours that would each have failed
quietly rather than loudly — this test pins both:
  * it reads its input as a VERBATIM transcript, so the "Read this warmly ...: " prefix the preview
    models took as direction would be SPOKEN at the top of every clip (config.TTS_STYLE_IN_PROMPT);
  * it returns a RIFF/WAV container, not headerless PCM, and a WAV header fed to the mp3 encoder as
    samples is a click at the front of every clip (tts._decode_audio).

  T1  DECODE — offline. Both payload shapes decode to the same samples, and the model chain has a
      real fallback (two distinct ids). Goes red in CI even on a day Gemini is unreachable.
  T2  EVERY MODEL ANSWERS — live. Each id in config.TTS_MODELS, called through the PRODUCTION
      tts._synthesize_with with a production-shaped style, returns audio of a plausible length for
      the sample sentence. A FALLBACK THAT HAS ITSELF BEEN RETIRED IS THE SAME OUTAGE ONE MORNING
      LATER, so the fallback is checked too, not only the primary.
  T3  PREMISE — live, reported and NOT failed on: the same sentence on the primary with the style
      forced INTO the text. If 3.8 still reads that aloud, the duration jumps; this is the measurement
      that justifies TTS_STYLE_IN_PROMPT, re-taken weekly in case Google changes it back.

A model that answers 404 / "not found" is a FAIL (the retirement signal). A transient error (429,
5xx, timeout — tts._tts_transient) is INFRA, exit 3: quota is not drift.

NEGATIVE CONTROLS (`TTS_CONTROL=<mode>`):
  dead-fallback -> T2 red. Swaps the fallback for an id that does not exist: proves T2 tests EVERY
                   model and not just the one that answered first.
  raw-wav       -> T1 red. Neutralises the WAV decode: proves T1 would catch the click regressing.

  BRIEFING_SMOKE_ALLOW_DEV=true  required, like every test here. GEMINI_API_KEY for T2/T3.
Read-only (writes no files). Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
"""
import io
import os
import struct
import sys
import wave

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr)
    sys.exit(2)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

try:
    from scripts import config, tts                 # noqa: E402
except Exception as e:                              # noqa: BLE001 - any import failure is INFRA
    print(f"INFRA: could not import the production surface ({type(e).__name__}: {e})", file=sys.stderr)
    sys.exit(3)

CONTROL = os.environ.get("TTS_CONTROL", "").strip()
if CONTROL == "dead-fallback":
    config.TTS_MODELS = (config.TTS_MODELS[0], "gemini-0.0-no-such-model-tts")
elif CONTROL == "raw-wav":
    tts._decode_audio = lambda data, mime: (data, 24000)
elif CONTROL:
    print(f"REFUSED: unknown TTS_CONTROL {CONTROL!r}", file=sys.stderr)
    sys.exit(2)

# ~14 words: about 4-5 s spoken. The style prefix used in production is ~15 more words, so a model
# that reads it aloud roughly doubles the clip — the bounds below sit between the two.
SAMPLE = "Good morning. Markets were mixed overnight, and the ten year yield held steady."
STYLE = "Read this morning news briefing aloud in a warm, clear, unhurried news-anchor voice: "
MIN_S, MAX_S = 1.5, 8.5

FAILURES, NOTES = [], []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --- T1 offline ------------------------------------------------------------------------------------
print("T1  decode + chain (offline)")
pcm = struct.pack("<2400h", *[(i * 37) % 3000 - 1500 for i in range(2400)])
buf = io.BytesIO()
with wave.open(buf, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(24000)
    w.writeframes(pcm)
got_wav = tts._decode_audio(buf.getvalue(), "audio/wav")
got_l16 = tts._decode_audio(pcm, "audio/L16;codec=pcm;rate=24000")
check("a WAV payload decodes to its samples, header stripped", got_wav == (pcm, 24000),
      f"{len(got_wav[0])} bytes vs {len(pcm)}")
check("a headerless L16 payload passes through with its rate", got_l16 == (pcm, 24000))
check("the model chain has a distinct fallback", len(set(config.TTS_MODELS)) >= 2,
      str(config.TTS_MODELS))

# --- T2/T3 live ------------------------------------------------------------------------------------
if not os.environ.get("GEMINI_API_KEY"):
    print("REFUSED: GEMINI_API_KEY not set — T2/T3 (the live half) cannot run", file=sys.stderr)
    sys.exit(1 if FAILURES else 2)

infra = []
print(f"\nT2  every configured model answers through the production call (voice {config.TTS_VOICE})")
for model in config.TTS_MODELS:
    try:
        out_pcm, rate = tts._synthesize_with(model, SAMPLE, STYLE)
        secs = len(out_pcm) / 2 / rate
        check(f"{model} returns {MIN_S}-{MAX_S}s for the sample", MIN_S <= secs <= MAX_S,
              f"{secs:.1f}s at {rate} Hz; style-in-prompt={config.TTS_STYLE_IN_PROMPT(model)}")
    except Exception as e:                          # noqa: BLE001
        if tts._tts_transient(e):
            infra.append(f"{model}: {type(e).__name__}: {e}")
            print(f"  INFRA {model}: {type(e).__name__}: {e}")
        else:
            check(f"{model} answers", False, f"{type(e).__name__}: {str(e)[:200]}")

primary = config.TTS_MODELS[0]
if not config.TTS_STYLE_IN_PROMPT(primary) and not CONTROL:
    print(f"\nT3  premise: does {primary} SPEAK a style prefix? (measured, never failed on)")
    real = config.TTS_STYLE_IN_PROMPT
    config.TTS_STYLE_IN_PROMPT = lambda m: True
    try:
        leak_pcm, leak_rate = tts._synthesize_with(primary, SAMPLE, STYLE)
        secs = len(leak_pcm) / 2 / leak_rate
        NOTES.append(f"NOTE T3 with the style forced into the text: {secs:.1f}s "
                     f"({'READ ALOUD — keep it out of the prompt' if secs > MAX_S else 'not read aloud'})")
    except Exception as e:                          # noqa: BLE001
        NOTES.append(f"NOTE T3 skipped: {type(e).__name__}: {e}")
    finally:
        config.TTS_STYLE_IN_PROMPT = real

for n in NOTES:
    print(n)
if FAILURES:
    print("FAIL: 16-tts-model — " + "; ".join(FAILURES), file=sys.stderr)
    sys.exit(1)
if infra:
    print("INFRA: 16-tts-model could not reach " + "; ".join(infra), file=sys.stderr)
    sys.exit(3)
if CONTROL:
    print(f"NOTE: control {CONTROL!r} did NOT go red — it has stopped measuring anything", file=sys.stderr)
    sys.exit(1)
print(f"PASS: 16-tts-model — T1..T2 ({len(config.TTS_MODELS)} models answer in {config.TTS_VOICE})")
