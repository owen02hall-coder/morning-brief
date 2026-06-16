"""ntfy push notifications: the morning 'ready' drop and a self-monitoring health ping.

The topic is read from NTFY_TOPIC (a secret) and is never exposed client-side. Notification
failures are non-fatal — a missed push must not crash the run.
"""
import os
import urllib.request

from . import config


def _publish(title, message, priority="default", click=None):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("notify: NTFY_TOPIC not set — skipping push")
        return False
    headers = {"Title": title, "Priority": priority, "User-Agent": config.USER_AGENT}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"{config.NTFY_BASE}/{topic}", data=message.encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return 200 <= r.status < 300
    except Exception as e:  # never let a notification failure crash the briefing
        print(f"notify: push failed ({e})")
        return False


def morning_ready(headline):
    """Daily 'your briefing is ready' push that taps through to the PWA."""
    if "example.github.io" in config.PAGES_URL:
        # Loud warning: the tap-through link is the placeholder, so the push will dead-end.
        print("notify: WARNING PAGES_URL is still the placeholder — set the PAGES_URL repo "
              "variable so the notification opens your real page.")
    return _publish("Morning Briefing", headline, priority="default", click=config.PAGES_URL)


def health(message, ok=True):
    """Self-monitoring: loud high-priority on failure, low-priority on partial degradation."""
    if ok:
        return _publish("Briefing degraded", message, priority="low")
    return _publish("Briefing FAILED", message, priority="high")
