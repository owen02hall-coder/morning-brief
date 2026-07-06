"""ntfy push notifications: the morning 'ready' drop and a self-monitoring health ping.

The topic is read from NTFY_TOPIC (a secret) and is never exposed client-side. Notification
failures are non-fatal — a missed push must not crash the run.
"""
import os
import time
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
    # High-priority pushes are ALERTS (failure/blackout escalations): retry once, and if delivery
    # still fails say so unmissably in the job log — the run must not crash over a push, but a
    # swallowed alert would mean the monitoring itself failed silently.
    attempts = 2 if priority == "high" else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if 200 <= r.status < 300:
                    return True
            last_err = f"HTTP {r.status}"
        except Exception as e:  # never let a notification failure crash the briefing
            last_err = e
        if attempt < attempts - 1:
            time.sleep(3)
    print(f"notify: push failed ({last_err})")
    if priority == "high":
        print(f"notify: ALERT DELIVERY FAILED — a high-priority alert ('{title}: {message}') "
              "could not reach ntfy; check the topic and ntfy.sh status.")
    return False


def morning_ready(headline):
    """Daily 'your briefing is ready' push that taps through to the PWA."""
    if "example.github.io" in config.PAGES_URL:
        # Loud warning: the tap-through link is the placeholder, so the push will dead-end.
        print("notify: WARNING PAGES_URL is still the placeholder — set the PAGES_URL repo "
              "variable so the notification opens your real page.")
    return _publish("Morning Briefing", headline, priority="default", click=config.PAGES_URL)


def breadth_alert(message):
    """Oversold market-breadth nag — high priority so it lands like the alert it is."""
    return _publish("Market breadth OVERSOLD", message, priority="high", click=config.PAGES_URL)


def health(message, ok=True):
    """Self-monitoring: loud high-priority on failure, low-priority on partial degradation."""
    if ok:
        return _publish("Briefing degraded", message, priority="low")
    return _publish("Briefing FAILED", message, priority="high")


def main(argv):
    """CLI entry so the workflow can send the ready-push AFTER the publish leg succeeds.

    `python -m scripts.notify ready` reads the headline the build wrote to config.HEADLINE_PATH
    and sends the morning push. Exits 0 with a no-op message when the file is absent (no-op
    build day) so the workflow step needs no existence check of its own.
    """
    if not argv or argv[0] != "ready":
        print("usage: python -m scripts.notify ready")
        return 2
    try:
        with open(config.HEADLINE_PATH, encoding="utf-8") as f:
            headline = f.read().strip()
    except FileNotFoundError:
        print("notify: no headline file — nothing was built this run, skipping ready push")
        return 0
    if not headline:
        headline = "Your morning briefing is ready."
    morning_ready(headline)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
