"""Shared application state, stored in ``application.bot_data['state']``."""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .ai import AIService
from .cache import TTLCache
from .config import Settings
from .content import ContentLibrary
from .security import TokenBucketLimiter
from .store import Store

if TYPE_CHECKING:  # pragma: no cover
    from telegram.ext import ContextTypes


@dataclass(slots=True)
class Stats:
    started_at: float = field(default_factory=time.time)
    commands: Counter = field(default_factory=Counter)
    errors: int = 0
    messages: int = 0
    ai_chats: int = 0
    callbacks: int = 0

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at

    @property
    def total_commands(self) -> int:
        return sum(self.commands.values())


@dataclass
class AppState:
    settings: Settings
    store: Store
    ai: AIService
    content: ContentLibrary
    limiter: TokenBucketLimiter
    stats: Stats = field(default_factory=Stats)
    games: TTLCache = field(default_factory=lambda: TTLCache(ttl=1800, maxsize=5000))
    http_cache: TTLCache = field(default_factory=lambda: TTLCache(ttl=300, maxsize=512))
    _locks: dict[int, asyncio.Lock] = field(default_factory=dict)

    def user_lock(self, user_id: int) -> asyncio.Lock:
        """Per-user lock so concurrent updates cannot interleave a user's chat history."""
        lock = self._locks.get(user_id)
        if lock is None:
            if len(self._locks) > 5000:
                for key in [k for k, v in self._locks.items() if not v.locked()][:2500]:
                    self._locks.pop(key, None)
            lock = self._locks[user_id] = asyncio.Lock()
        return lock


def get_state(context: "ContextTypes.DEFAULT_TYPE | Any") -> AppState:
    return context.application.bot_data["state"]
