"""Minimal Twelve Data REST client.

NOTE: NOT used by the v1 pipeline. v1 takes all four headline numbers from FRED (see
scripts/data/market.py), because Twelve Data's free tier gates index symbols. This client is
STAGED FOR v2 breadth (per-constituent quotes), where it will be extended to handle the
8-credits/minute free-tier limit. Kept here so v2 starts from a proven client shape.
"""
import os
import time
import json
import urllib.parse
import urllib.request
import urllib.error

BASE = "https://api.twelvedata.com"


class TwelveDataError(RuntimeError):
    pass


def _api_key():
    key = os.environ.get("TWELVEDATA_API_KEY")
    if not key:
        raise TwelveDataError("TWELVEDATA_API_KEY not set")
    return key


def _get(path, params, timeout=20):
    params = {**params, "apikey": _api_key()}
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def quote(symbol, retries=2):
    """Return the parsed quote dict for one symbol, or None if it does not resolve.

    Retries once on a transient 429 (rate limit) with a short wait; raises TwelveDataError on
    repeated failure so the caller can degrade the section to 'unavailable'.
    """
    for attempt in range(retries + 1):
        try:
            data = _get("quote", {"symbol": symbol})
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(8)  # free tier resets per minute; brief wait then retry
                continue
            raise TwelveDataError(f"HTTP {e.code} for {symbol}")
        except urllib.error.URLError as e:
            raise TwelveDataError(f"network error for {symbol}: {e}")
        # Twelve Data signals problems with a JSON {"code":..., "status":"error"} body
        if isinstance(data, dict) and data.get("status") == "error":
            if data.get("code") == 429 and attempt < retries:
                time.sleep(8)
                continue
            return None
        if isinstance(data, dict) and data.get("close"):
            return data
        return None
    return None
