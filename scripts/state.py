"""Persisted run state (committed to the repo, not served on Pages).

v1 only needs `last_run` — always rewritten to today so there is a daily renewing commit, which
keeps the scheduled GitHub Actions workflow from auto-disabling after 60 idle days. v2 breadth
alert state will live here too.
"""
import json
import os

from . import config


def load():
    try:
        with open(config.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_run": None}  # cold-start default


def save(state, today):
    state = {**state, "last_run": today}  # always refresh → guarantees a daily commit
    os.makedirs(os.path.dirname(config.STATE_PATH), exist_ok=True)
    with open(config.STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return state
