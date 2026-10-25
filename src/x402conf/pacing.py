"""Polite pacing for live targets.

Every request the CLI sends to a live target goes through one Pacer: at least `min_interval` seconds between the
start of one request and the next (5 s by default), at most `max_requests` requests in the run when a cap is set, and
one log line per request on stderr. Loopback targets (127.0.0.0/8, ::1, localhost) are counted and logged but not
spaced, so local servers and CI runs are not slowed down. A request that would go over the cap is not sent:
RequestBudgetExceeded is raised before anything leaves the machine, and the caller reports the target as skipped."""

from __future__ import annotations

import ipaddress
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, TextIO

DEFAULT_MIN_INTERVAL = 5.0


class RequestBudgetExceeded(RuntimeError):
    """The next request would exceed --max-requests; it was not sent."""


def is_loopback(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Pacer:
    def __init__(self, min_interval: float = DEFAULT_MIN_INTERVAL, max_requests: int | None = None, *,
                 log: TextIO | None = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, wall: Callable[[], float] = time.time) -> None:
        if min_interval < 0:
            raise ValueError("--min-interval must be 0 or more seconds")
        if max_requests is not None and max_requests < 1:
            raise ValueError("--max-requests must be at least 1")
        self.min_interval = float(min_interval)
        self.max_requests = max_requests
        self.log = log
        self._clock, self._sleep, self._wall = clock, sleep, wall
        self._last: float | None = None
        self.requests: list[dict[str, Any]] = []

    def before(self, method: str, url: str, note: str = "") -> None:
        """Wait out the interval and record one request, or raise RequestBudgetExceeded without recording it."""
        n = len(self.requests) + 1
        if self.max_requests is not None and n > self.max_requests:
            raise RequestBudgetExceeded(f"--max-requests {self.max_requests} reached; {method} {url} was not sent")
        waited = 0.0
        if not is_loopback(url) and self._last is not None:
            gap = self._last + self.min_interval - self._clock()
            if gap > 0:
                self._sleep(gap)
                waited = gap
        self._last = self._clock()
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._wall()))
        entry: dict[str, Any] = {"n": n, "at": at, "method": method, "url": url, "waited_s": round(waited, 3)}
        if note:
            entry["note"] = note
        self.requests.append(entry)
        cap = f" of at most {self.max_requests}" if self.max_requests is not None else ""
        print(f"x402conf: request {n}{cap} at {at}: {method} {url}" + (f" ({note})" if note else "")
              + (f", after waiting {waited:.1f} s" if waited else ""), file=self.log or sys.stderr)

    def wrap(self, opener: Callable[..., Any] | None = None, note: str = "") -> Callable[..., Any]:
        """An opener with urllib.request.urlopen's signature that paces every request it sends."""
        base = opener or urllib.request.urlopen

        def paced(req: Any, *a: Any, **kw: Any) -> Any:
            url = req.full_url if hasattr(req, "full_url") else str(req)
            method = req.get_method() if hasattr(req, "get_method") else "GET"
            self.before(method, url, note)
            return base(req, *a, **kw)

        return paced

    def summary(self) -> dict[str, Any]:
        return {"min_interval_s": self.min_interval, "max_requests": self.max_requests,
                "sent": len(self.requests), "requests": list(self.requests)}
