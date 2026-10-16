"""Small thread-safe TTL cache used for API responses and short-lived game state."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")
_MISSING = object()


class TTLCache(Generic[K, V]):
    """LRU + TTL cache.  ``get`` returns ``default`` for missing or expired keys."""

    def __init__(
        self,
        ttl: float,
        maxsize: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl <= 0 or maxsize <= 0:
            raise ValueError("ttl and maxsize must be positive")
        self._ttl = ttl
        self._maxsize = maxsize
        self._clock = clock
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K, default=None, *, refresh: bool = False):
        now = self._clock()
        with self._lock:
            item = self._data.get(key, _MISSING)
            if item is _MISSING:
                return default
            expires, value = item  # type: ignore[misc]
            if expires <= now:
                del self._data[key]
                return default
            self._data.move_to_end(key)
            if refresh:
                self._data[key] = (now + self._ttl, value)
            return value

    def set(self, key: K, value: V, ttl: float | None = None) -> None:
        now = self._clock()
        with self._lock:
            self._data[key] = (now + (ttl if ttl is not None else self._ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def pop(self, key: K, default=None):
        with self._lock:
            item = self._data.pop(key, _MISSING)
        if item is _MISSING:
            return default
        expires, value = item  # type: ignore[misc]
        return value if expires > self._clock() else default

    def purge(self) -> int:
        """Drop expired entries; returns how many were removed."""
        now = self._clock()
        with self._lock:
            dead = [k for k, (exp, _) in self._data.items() if exp <= now]
            for key in dead:
                del self._data[key]
            return len(dead)

    def __contains__(self, key: object) -> bool:
        return self.get(key, _MISSING) is not _MISSING  # type: ignore[arg-type]

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


async def cached_call(cache: TTLCache, key, factory: Callable[[], Awaitable]):
    """Return the cached value for ``key`` or await ``factory()`` and cache the result."""
    hit = cache.get(key, _MISSING)
    if hit is not _MISSING:
        return hit
    value = await factory()
    cache.set(key, value)
    return value
