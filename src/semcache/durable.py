"""Telling GitHub's "slow down" apart from real failures, so the caller (a Temporal activity,
see seeding.py) can let Temporal do the waiting and retrying instead of sleeping in a loop."""

import threading
import time

import httpx


class RateLimited(RuntimeError):
    """GitHub asked us to wait `wait` seconds. A RuntimeError so the callers that already treat a
    rate limit as one (details, chat) keep working."""

    def __init__(self, wait: float):
        super().__init__(f"rate limited for {wait:.0f}s")
        self.wait = wait


class Unavailable(Exception):
    """A server error or network failure: worth retrying with backoff."""


def rate_limit_wait(r: httpx.Response, now: float | None = None) -> float | None:
    """Seconds GitHub wants us to wait, or None if this response is not a rate limit.

    A 429, or a 403 that carries Retry-After or says the quota is spent, is a rate limit. Any
    other 403 (a blocked repo, say) is not, so it is never retried.
    """
    if r.status_code not in (403, 429):
        return None
    if "retry-after" in r.headers:
        try:
            return max(float(r.headers["retry-after"]), 1.0)
        except ValueError:
            return 60.0
    if r.headers.get("x-ratelimit-remaining") == "0":
        reset = float(r.headers.get("x-ratelimit-reset", 0))
        return max(reset - (time.time() if now is None else now), 0.0) + 1.0
    return 60.0 if r.status_code == 429 else None


def request(client: httpx.Client, url: str, *, params: dict | None = None) -> httpx.Response:
    """One GET, no retries. Returns the response (a 404 is an answer, not an error); raises
    RateLimited or Unavailable for the cases a retry could fix."""
    try:
        r = client.get(url, params=params)
    except httpx.TransportError as e:
        raise Unavailable(f"{url}: {type(e).__name__}") from e
    wait = rate_limit_wait(r)
    if wait is not None:
        raise RateLimited(wait)
    if r.status_code >= 500:
        raise Unavailable(f"{url}: HTTP {r.status_code}")
    return r


# One cool-down shared by every thread in the process. Once GitHub says "slow down", calls to
# api.github.com fail locally until the time it named has passed, so a search made meanwhile does
# not spend requests (or extend the penalty) on a quota that is already gone.
_lock = threading.Lock()
_blocked_until = 0.0


def blocked_for(now: float | None = None) -> float:
    """Seconds left on the cool-down, or 0.0 when GitHub may be called."""
    with _lock:
        return max(_blocked_until - (time.time() if now is None else now), 0.0)


def note_rate_limit(wait: float, now: float | None = None) -> None:
    """Start (or extend, never shorten) the cool-down."""
    global _blocked_until
    with _lock:
        _blocked_until = max(_blocked_until, (time.time() if now is None else now) + wait)


def _gate_request(request: httpx.Request) -> None:
    if request.url.host == "api.github.com" and (left := blocked_for()) > 0:
        raise RateLimited(left)


def _watch_response(response: httpx.Response) -> None:
    if response.request.url.host == "api.github.com" and (wait := rate_limit_wait(response)):
        note_rate_limit(wait)


# Pass as httpx.Client(event_hooks=GATE) on any client that calls api.github.com. raw.github
# usercontent is not rate limited the same way, so it is left alone.
GATE = {"request": [_gate_request], "response": [_watch_response]}
