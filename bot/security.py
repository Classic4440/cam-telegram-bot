"""Abuse controls: token-bucket rate limiting and input sanitising."""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TokenBucketLimiter:
    """Per-key token bucket.

    ``consume`` returns ``0.0`` when the request is allowed, otherwise the number of seconds the caller
    must wait.  Buckets that have fully refilled are pruned so memory stays bounded.
    """

    def __init__(
        self,
        capacity: int,
        refill_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        if capacity <= 0 or refill_seconds <= 0:
            raise ValueError("capacity and refill_seconds must be positive")
        self.capacity = float(capacity)
        self.rate = 1.0 / refill_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[int, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def consume(self, key: int, cost: float = 1.0) -> float:
        cost = min(float(cost), self.capacity)
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                if len(self._buckets) > self._max_keys:
                    self._prune(now)
                return 0.0
            self._buckets[key] = (tokens, now)
            return (cost - tokens) / self.rate

    def _prune(self, now: float) -> None:
        full = [
            k for k, (tokens, last) in self._buckets.items()
            if tokens + (now - last) * self.rate >= self.capacity
        ]
        for key in full:
            del self._buckets[key]


def sanitize_text(text: str, limit: int) -> str:
    """Strip control characters and cap length (defence against log/prompt noise and huge payloads)."""
    cleaned = _CONTROL_CHARS.sub("", text).strip()
    return cleaned[:limit]
