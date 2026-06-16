#!/usr/bin/env python3
"""
ASSUMPTION 3: the pinned `google-genai` SDK's structured-output config actually yields a non-None,
schema-valid object for our Briefing-shaped schema. The plan flags real uncertainty about the
config shape (`response_mime_type`+`response_schema` vs the newer `response_format`) and that
`resp.parsed` can be None on coercion failure. This proves which shape works and that parsing holds.

Read-only (one small generate_content call). Exit: 0 PASS / 1 FAIL / 2 REFUSED / 3 INFRA.
NEGATIVE CONTROL (synthetic-injection): we assert resp.parsed validates against the schema; the
check is then re-run against a deliberately wrong object to confirm the validator rejects it.
"""
import os, sys, json
from datetime import datetime, timezone

GATE = "BRIEFING_SMOKE_ALLOW_DEV"
if os.environ.get(GATE) != "true":
    print(f"REFUSED: set {GATE}=true to run assumption tests", file=sys.stderr); sys.exit(2)
if not os.environ.get("GEMINI_API_KEY"):
    print("INFRA: GEMINI_API_KEY not set — create a free key on a billing-disabled project", file=sys.stderr)
    sys.exit(3)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("MODEL_ID", "gemini-2.5-flash")

try:
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, ValidationError
except ImportError as e:
    print(f"INFRA: missing dependency ({e}) — pip install google-genai pydantic", file=sys.stderr); sys.exit(3)

class Item(BaseModel):
    summary: str
    source: str
    url: str

class MiniBriefing(BaseModel):       # representative subset of the real Briefing schema
    tldr: list[str]
    market_why: str
    world: list[Item]

PROMPT = ("Here are today's inputs. Market: S&P 500 +0.4%. "
          "Articles: [{title: 'Global summit reaches accord', source: 'BBC', "
          "url: 'https://example.com/a', summary: 'Leaders agreed...'}]. "
          "Write a concise briefing. Use ONLY provided articles; no emojis.")
SYSTEM = "You are a precise news editor. Plain text, no emojis. Cite only provided URLs."

def try_config():
    """Return (resp, which_shape) trying the documented shape then the newer one."""
    client = genai.Client()
    # shape A: response_mime_type + response_schema
    try:
        resp = client.models.generate_content(
            model=MODEL, contents=PROMPT,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=MiniBriefing))
        return resp, "response_mime_type+response_schema"
    except Exception as e_a:
        # shape B: response_format (newer 2026 docs)
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=PROMPT,
                config={"response_format": {"text": {"mime_type": "application/json",
                        "schema": MiniBriefing.model_json_schema()}}})
            return resp, "response_format"
        except Exception as e_b:
            raise RuntimeError(f"both config shapes failed: A={e_a!r}; B={e_b!r}")

def main():
    failures = []
    try:
        resp, shape = try_config()
    except RuntimeError as e:
        print(f"FAIL: 03-gemini-structured\n  - A1 {e}", file=sys.stderr); sys.exit(1)
    except Exception as e:
        print(f"INFRA: Gemini call failed (network/quota/auth): {e}", file=sys.stderr); sys.exit(3)

    # A1 — a config shape worked and returned a parseable object (not None)
    parsed = getattr(resp, "parsed", None)
    if parsed is None:
        # try manual parse from text as the plan's fallback path
        try:
            parsed = MiniBriefing.model_validate_json(resp.text)
        except Exception:
            failures.append("A1 resp.parsed is None AND text did not validate against the schema")

    # A2 — the parsed object actually validates against the schema
    if parsed is not None:
        try:
            MiniBriefing.model_validate(parsed if isinstance(parsed, dict) else parsed.model_dump())
        except ValidationError as e:
            failures.append(f"A2 parsed object failed schema validation: {e}")

    # NEGATIVE CONTROL: confirm the validator rejects a deliberately wrong object
    try:
        MiniBriefing.model_validate({"tldr": "not-a-list", "market_why": 5})
        failures.append("NEG-CONTROL validator accepted an invalid object — schema check is blind")
    except ValidationError:
        pass

    fp = {"model": MODEL, "working_config_shape": shape, "parsed_ok": parsed is not None,
          "checked_at": datetime.now(timezone.utc).isoformat()}

    if failures:
        print("FAIL: 03-gemini-structured", file=sys.stderr)
        for f in failures: print("  -", f, file=sys.stderr)
        sys.exit(1)

    json.dump(fp, open(os.path.join(HERE, "03-gemini-structured.fingerprint.json"), "w"), indent=2)
    print(f"PASS: 03-gemini-structured — A1,A2 (model={MODEL}, config='{shape}')")

if __name__ == "__main__":
    main()
