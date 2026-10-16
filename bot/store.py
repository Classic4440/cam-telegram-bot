"""Persistence layer with circuit breaker and in-memory fallback. [439 lines]

* ``MemoryBackend``   - process-local fallback (also used by tests).  Data is lost on restart.
* ``SupabaseBackend`` - durable Postgres via Supabase (see ``supabase/schema.sql``).
* ``Store``           - async facade.  Calls Supabase in a worker thread, trips a circuit breaker after
                        repeated failures, and transparently falls back to memory so a database
                        outage degrades features instead of crashing the bot.
All backend methods are synchronous; the facade owns threading.
Includes: history, profiles, XP, todos, notes, reminders with per-user locking and batch flushing.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import math
import threading
import time
from collections import defaultdict, deque
from typing import Any

logger = logging.getLogger(__name__)


def level_for(xp: int) -> int:
    """Level curve: level N needs 40*(N-1)^2 total xp."""
    return int(math.sqrt(max(0, xp) / 40)) + 1


def xp_for_level(level: int) -> int:
    return 40 * (max(1, level) - 1) ** 2


# ======================================================================================
# in-memory backend
# ======================================================================================
class MemoryBackend:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ids = itertools.count(1)
        self.history: dict[int, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=200))
        self.profiles: dict[int, dict[str, Any]] = {}
        self.todos: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.notes: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self.reminders: dict[int, dict[str, Any]] = {}

    # history -------------------------------------------------------------------------
    def load_history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        with self._lock:
            return list(self.history[user_id])[-limit:] if limit > 0 else []

    def save_turn(self, user_id: int, user_text: str, reply: str) -> None:
        with self._lock:
            self.history[user_id].append({"role": "user", "content": user_text})
            self.history[user_id].append({"role": "assistant", "content": reply})

    def clear_history(self, user_id: int) -> None:
        with self._lock:
            self.history.pop(user_id, None)

    # profiles: XP, leaderboard, persona -----------------------------------------------
    def get_profile(self, user_id: int) -> dict[str, Any] | None:
        with self._lock:
            profile = self.profiles.get(user_id)
            return dict(profile) if profile else None

    def upsert_profile(self, user_id: int, **fields: Any) -> None:
        with self._lock:
            profile = self.profiles.setdefault(user_id, {"user_id": user_id, "xp": 0, "persona": "default"})
            profile.update({k: v for k, v in fields.items() if v is not None})

    def flush_xp(self, deltas: dict[int, int], names: dict[int, str]) -> None:
        with self._lock:
            for user_id, amount in deltas.items():
                profile = self.profiles.setdefault(user_id, {"user_id": user_id, "xp": 0, "persona": "default"})
                profile["xp"] = int(profile.get("xp", 0)) + amount
                if names.get(user_id):
                    profile["username"] = names[user_id]

    def leaderboard(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = sorted(self.profiles.values(), key=lambda p: p.get("xp", 0), reverse=True)
            return [dict(r) for r in rows[:limit]]

    # todos ---------------------------------------------------------------------------
    def add_todo(self, user_id: int, text: str) -> dict[str, Any]:
        with self._lock:
            item = {"id": next(self._ids), "user_id": user_id, "text": text, "done": False}
            self.todos[user_id].append(item)
            return dict(item)

    def list_todos(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(t) for t in self.todos[user_id]]

    def set_todo_done(self, user_id: int, todo_id: int, done: bool = True) -> bool:
        with self._lock:
            for item in self.todos[user_id]:
                if item["id"] == todo_id:
                    item["done"] = done
                    return True
            return False

    def delete_todo(self, user_id: int, todo_id: int) -> bool:
        with self._lock:
            before = len(self.todos[user_id])
            self.todos[user_id] = [t for t in self.todos[user_id] if t["id"] != todo_id]
            return len(self.todos[user_id]) != before

    def clear_done_todos(self, user_id: int) -> int:
        with self._lock:
            before = len(self.todos[user_id])
            self.todos[user_id] = [t for t in self.todos[user_id] if not t["done"]]
            return before - len(self.todos[user_id])

    # notes ---------------------------------------------------------------------------
    def add_note(self, user_id: int, body: str) -> dict[str, Any]:
        with self._lock:
            item = {"id": next(self._ids), "user_id": user_id, "body": body}
            self.notes[user_id].append(item)
            return dict(item)

    def list_notes(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(n) for n in self.notes[user_id]]

    def delete_note(self, user_id: int, note_id: int) -> bool:
        with self._lock:
            before = len(self.notes[user_id])
            self.notes[user_id] = [n for n in self.notes[user_id] if n["id"] != note_id]
            return len(self.notes[user_id]) != before

    # reminders -----------------------------------------------------------------------
    def add_reminder(self, user_id: int, chat_id: int, text: str, due_ts: float) -> int:
        with self._lock:
            rid = next(self._ids)
            self.reminders[rid] = {
                "id": rid, "user_id": user_id, "chat_id": chat_id, "text": text,
                "due_ts": due_ts, "sent": False,
            }
            return rid

    def mark_reminder_sent(self, reminder_id: int) -> None:
        with self._lock:
            if reminder_id in self.reminders:
                self.reminders[reminder_id]["sent"] = True

    def pending_reminders(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.reminders.values() if not r["sent"]]

    def list_reminders(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(r) for r in self.reminders.values() if r["user_id"] == user_id and not r["sent"]]
            return sorted(rows, key=lambda r: r["due_ts"])

    def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        with self._lock:
            reminder = self.reminders.get(reminder_id)
            if reminder and reminder["user_id"] == user_id and not reminder["sent"]:
                reminder["sent"] = True
                return True
            return False


# [SupabaseBackend class omitted for brevity in Drive upload]
# See bot/store.py (full 439-line file) in project for complete implementation.
# SupabaseBackend: Thin wrapper around supabase-py, scoped queries by user_id,
# all same methods as MemoryBackend but persistent.


class _Breaker:
    """Circuit breaker: trips after 3 consecutive failures, cooldown 60s."""
    def __init__(self, threshold: int = 3, cooldown: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self.open_until

    def ok(self) -> None:
        self.failures = 0

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = time.monotonic() + self.cooldown
            self.failures = 0
            logger.error("Supabase circuit opened for %.0fs; using in-memory fallback", self.cooldown)


class Store:
    """Async facade over remote + memory backend with circuit breaker and XP batching."""

    def __init__(self, remote: Any = None) -> None:
        self.remote = remote
        self.local = MemoryBackend()
        self._breaker = _Breaker()
        self._xp: dict[int, int] = defaultdict(int)
        self._names: dict[int, str] = {}
        self._xp_lock = threading.Lock()

    @property
    def durable(self) -> bool:
        return self.remote is not None and self._breaker.allow()

    # [Full async implementation with per-user locking, XP buffering, and fallback]
    # See full bot/store.py for complete 200+ line Store class with all methods.
