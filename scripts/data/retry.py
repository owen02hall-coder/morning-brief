"""Bounded retry for the policy + mortgage HTTP legs. TRANSIENT failures only.

WHY THIS EXISTS, precisely. On 2026-08-03 (CI run 30859893450) federalregister.gov answered the
GitHub runner with HTTP 403 while the identical call succeeded from a home connection, and the very
next dispatch (30859980835) was green — transient rate limiting, after five dispatches hit that API
in one afternoon. As the code stood, one 403 made `policy._federal_candidates()` raise, so
`available=False`, the whole section rendered nothing, and the only signal was a LOW-priority
"degraded sections" ping. Silent-ish, and rate limits recur: silent + recurring is the two-part gate
this project uses to decide a failure earns a machine rather than a note.

WHAT IS RETRIED — and what deliberately is NOT.

  RETRIED  HTTP 403 / 408 / 425 / 429 and every 5xx; socket/read timeouts; connection resets,
           aborts and refusals; a body that ends mid-stream (IncompleteRead — a reset during the
           read, which is the same episode arriving one layer later).

  NOT      HTTP 400 and 404, and every other 4xx. This is the load-bearing half. A misspelled
           Federal Register agency slug returns **400, not an empty result set** (05-policy-
           sources.py's DISCOVERED PROPERTY), and the whole design leans on that: a typo fails
           LOUDLY instead of silently deleting one agency's coverage. Retrying it would spend 7
           seconds and two extra requests re-proving a permanent error and blunt the signal.
           Also not retried: anything that is not a transport failure at all — the ValueError
           `_federal_candidates()` raises on zero results, a JSON decode error, the PMMS read-cap
           ValueError. Those are decisions about a response that DID arrive; a second identical
           response cannot change them.

  403 IS IN THE RETRY SET AND 404 IS NOT, even though both are 4xx. That is the observed evidence,
  not a general rule about status classes: the 403 above came from a rate limiter, not from an
  authorization decision, and this whole module is a response to that one measurement. A 403 that
  is genuinely permanent costs 2 extra requests and 7 seconds once per run and then gives up.

THE PER-RUN BUDGET is the reason this is safe to switch on across a dozen possible requests. The
retried surface is PMMS + the Federal Register + up to 2 Utah list pages (the annual harvest chain)
+ up to 2 more (the one-time effective-date backfill) + up to 3 bill-JSON fetches + up to 3 HTML
fallbacks = 12. At 3 attempts each that would be ~900s of worst case inside briefing.yml's
`timeout-minutes: 10`, and a cancelled job ships no briefing at all — strictly worse than the
degraded section this module exists to prevent. So the EXTRA attempts are capped for the whole
process at `config.RETRY_EXTRA_ATTEMPT_BUDGET` (4):

    worst case added = 4 x config.POLICY_TIMEOUT (25s) + at most 14s of backoff = 114s (~1.9 min)

i.e. under 20% of the 600-second job cap, and only reachable if four separate requests each hang
for the full timeout. Ordering makes the budget land where it matters: `run()` calls
`mortgage.get_rate()` before `policy.get_policy()`, and PMMS is a single call that can consume at
most 2 extras, so at least 2 always remain for the federal leg. Utah's detail fetches come last and
are the first to be starved, which is the right priority — a dropped bill is one row out of an
annual backfill, a dropped federal fetch is the section.

The budget is PROCESS-global on purpose and needs no threading through call sites: one build is one
process (`python -m scripts.build_briefing`). `reset_budget()` exists for tests and for any caller
that runs more than one build in a process.

Every retry PRINTS its reason. That is required, not decoration: the point of the change is that a
rate-limit episode should be legible in the job log as a rate-limit episode, instead of the section
quietly rendering nothing.
"""
import http.client
import time
import urllib.error

from .. import config

# Transport-level statuses worth a second look. 403/429 are the measured rate-limit shapes, 408 is a
# server-side request timeout and 425 ("Too Early") is retry-by-definition. Every 5xx is included by
# range below.
TRANSIENT_STATUS = frozenset({403, 408, 425, 429})

_budget = config.RETRY_EXTRA_ATTEMPT_BUDGET


def reset_budget():
    """Restore the per-run extra-attempt budget. Production never needs this (one run = one
    process); tests and any multi-build process do."""
    global _budget
    _budget = config.RETRY_EXTRA_ATTEMPT_BUDGET
    return _budget


def remaining_budget():
    return _budget


def transient_reason(exc):
    """A short reason string when `exc` is a TRANSIENT transport failure, else None.

    None is the fail-closed answer: anything this function does not positively recognise is treated
    as permanent and re-raised immediately. Adding a class here is a deliberate act; a new exception
    type showing up in the wild must not silently start consuming the retry budget.

    Order matters. HTTPError subclasses URLError subclasses OSError, and ConnectionError and
    TimeoutError are also OSError — so the most specific test has to come first or a 404 would be
    classified by the URLError branch."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in TRANSIENT_STATUS or 500 <= exc.code < 600:
            return f"HTTP {exc.code}"
        return None                                  # 400 and 404 land here — LOUD, on purpose
    if isinstance(exc, TimeoutError):                # socket.timeout is TimeoutError since 3.10
        return "timeout"
    if isinstance(exc, ConnectionError):             # reset / aborted / refused / broken pipe,
        return type(exc).__name__                    # incl. http.client.RemoteDisconnected
    if isinstance(exc, http.client.IncompleteRead):  # the body ended mid-stream: a reset one layer up
        return "incomplete read"
    if isinstance(exc, urllib.error.URLError):
        # urllib wraps the real socket error in .reason for failures during connect.
        return transient_reason(exc.reason) if isinstance(exc.reason, BaseException) else None
    return None


def call(what, fn):
    """Run `fn()`, retrying it on transient failures. Returns fn()'s value or re-raises its error.

    `what` is the label the log lines carry, so a job log reads "retry: Federal Register — HTTP 403
    ..." rather than a bare stack trace. `fn` must be idempotent — every call site here is a GET.

    This function never swallows anything: the caller's existing degrade-and-log path still runs on
    the final failure, unchanged. All this changes is how many times the request is tried first."""
    global _budget
    attempts = max(1, int(config.RETRY_MAX_ATTEMPTS))
    backoff = config.RETRY_BACKOFF_SECONDS or (0,)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            reason = transient_reason(e)
            if reason is None:
                raise                       # permanent (400/404/parse/...): fail now, fail loudly
            if attempt >= attempts:
                print(f"retry: {what} — {reason} on attempt {attempt}/{attempts} "
                      f"({type(e).__name__}: {e}); no attempts left, giving up")
                raise
            if _budget <= 0:
                print(f"retry: {what} — {reason} on attempt {attempt}/{attempts} "
                      f"({type(e).__name__}: {e}); the per-run retry budget is spent, giving up to "
                      f"protect the job timeout")
                raise
            _budget -= 1
            delay = backoff[min(attempt - 1, len(backoff) - 1)]
            print(f"retry: {what} — {reason} on attempt {attempt}/{attempts} "
                  f"({type(e).__name__}: {e}); retrying in {delay}s "
                  f"(retry budget left: {_budget})")
            time.sleep(delay)
