"""Persistence layer.

* ``MemoryBackend``   - process-local fallback (also used by tests).  Data is lost on restart.
* ``SupabaseBackend`` - durable Postgres via Supabase (see ``supabase/schema.sql``).
* ``Store``           - async facade.  Calls Supabase in a worker thread, trips a circuit breaker after
                        repeated failures, and transparently falls back to memory so a database
                        outage degrades features instead of crashing the bot.

All backend methods are synchronous; the facade owns threading.
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

    # profiles ------------------------------------------------------------------------
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


# ======================================================================================
# supabase backend
# ======================================================================================
def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _parse_iso(value: str) -> float:
    from datetime import datetime, timezone

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


class SupabaseBackend:
    """Thin synchronous wrapper around supabase-py.  Every query is scoped by ``user_id``."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _t(self, name: str):
        return self.client.table(name)

    # history -------------------------------------------------------------------------
    def load_history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        if limit <= 0:
            return []
        rows = (
            self._t("chat_history").select("role, content").eq("user_id", user_id)
            .order("created_at", desc=True).order("id", desc=True).limit(limit).execute().data or []
        )
        return [
            {"role": r["role"], "content": r["content"]}
            for r in reversed(rows)
            if r.get("role") in {"user", "assistant"} and isinstance(r.get("content"), str)
        ]

    def save_turn(self, user_id: int, user_text: str, reply: str) -> None:
        self._t("chat_history").insert([
            {"user_id": user_id, "role": "user", "content": user_text},
            {"user_id": user_id, "role": "assistant", "content": reply},
        ]).execute()

    def clear_history(self, user_id: int) -> None:
        self._t("chat_history").delete().eq("user_id", user_id).execute()

    # profiles ------------------------------------------------------------------------
    def get_profile(self, user_id: int) -> dict[str, Any] | None:
        rows = self._t("profiles").select("*").eq("user_id", user_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def upsert_profile(self, user_id: int, **fields: Any) -> None:
        payload = {"user_id": user_id, **{k: v for k, v in fields.items() if v is not None}}
        self._t("profiles").upsert(payload, on_conflict="user_id").execute()

    def flush_xp(self, deltas: dict[int, int], names: dict[int, str]) -> None:
        for user_id, amount in deltas.items():
            self.client.rpc(
                "add_xp", {"p_user_id": user_id, "p_username": names.get(user_id), "p_amount": amount}
            ).execute()

    def leaderboard(self, limit: int) -> list[dict[str, Any]]:
        return (
            self._t("profiles").select("user_id, username, xp").order("xp", desc=True).limit(limit).execute().data or []
        )

    # todos ---------------------------------------------------------------------------
    def add_todo(self, user_id: int, text: str) -> dict[str, Any]:
        return self._t("todos").insert({"user_id": user_id, "text": text}).execute().data[0]

    def list_todos(self, user_id: int) -> list[dict[str, Any]]:
        return self._t("todos").select("id, text, done").eq("user_id", user_id).order("id").limit(100).execute().data or []

    def set_todo_done(self, user_id: int, todo_id: int, done: bool = True) -> bool:
        data = self._t("todos").update({"done": done}).eq("user_id", user_id).eq("id", todo_id).execute().data
        return bool(data)

    def delete_todo(self, user_id: int, todo_id: int) -> bool:
        return bool(self._t("todos").delete().eq("user_id", user_id).eq("id", todo_id).execute().data)

    def clear_done_todos(self, user_id: int) -> int:
        return len(self._t("todos").delete().eq("user_id", user_id).eq("done", True).execute().data or [])

    # notes ---------------------------------------------------------------------------
    def add_note(self, user_id: int, body: str) -> dict[str, Any]:
        return self._t("notes").insert({"user_id": user_id, "body": body}).execute().data[0]

    def list_notes(self, user_id: int) -> list[dict[str, Any]]:
        return self._t("notes").select("id, body").eq("user_id", user_id).order("id").limit(100).execute().data or []

    def delete_note(self, user_id: int, note_id: int) -> bool:
        return bool(self._t("notes").delete().eq("user_id", user_id).eq("id", note_id).execute().data)

    # reminders -----------------------------------------------------------------------
    def add_reminder(self, user_id: int, chat_id: int, text: str, due_ts: float) -> int:
        row = self._t("reminders").insert(
            {"user_id": user_id, "chat_id": chat_id, "text": text, "due_at": _iso(due_ts)}
        ).execute().data[0]
        return int(row["id"])

    def mark_reminder_sent(self, reminder_id: int) -> None:
        self._t("reminders").update({"sent": True}).eq("id", reminder_id).execute()

    def _reminder_rows(self, query) -> list[dict[str, Any]]:
        rows = query.execute().data or []
        return [{**r, "due_ts": _parse_iso(r["due_at"])} for r in rows]

    def pending_reminders(self) -> list[dict[str, Any]]:
        return self._reminder_rows(
            self._t("reminders").select("id, user_id, chat_id, text, due_at").eq("sent", False).limit(1000)
        )

    def list_reminders(self, user_id: int) -> list[dict[str, Any]]:
        return self._reminder_rows(
            self._t("reminders").select("id, user_id, chat_id, text, due_at")
            .eq("user_id", user_id).eq("sent", False).order("due_at").limit(50)
        )

    def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        data = (
            self._t("reminders").update({"sent": True}).eq("user_id", user_id).eq("id", reminder_id)
            .eq("sent", False).execute().data
        )
        return bool(data)


# ======================================================================================
# async facade with circuit breaker
# ======================================================================================
class _Breaker:
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
    """Async facade over a remote backend with an in-memory safety net."""

    def __init__(self, remote: SupabaseBackend | None = None) -> None:
        self.remote = remote
        self.local = MemoryBackend()
        self._breaker = _Breaker()
        self._xp: dict[int, int] = defaultdict(int)
        self._names: dict[int, str] = {}
        self._xp_lock = threading.Lock()

    @property
    def durable(self) -> bool:
        return self.remote is not None and self._breaker.allow()

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.remote is not None and self._breaker.allow():
            try:
                result = await asyncio.to_thread(getattr(self.remote, method), *args, **kwargs)
                self._breaker.ok()
                return result
            except Exception:  # noqa: BLE001 - any backend failure degrades to memory
                self._breaker.fail()
                logger.exception("Supabase call %s failed; falling back to memory", method)
        return getattr(self.local, method)(*args, **kwargs)

    # history
    async def load_history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        return await self._call("load_history", user_id, limit)

    async def save_turn(self, user_id: int, user_text: str, reply: str) -> None:
        await self._call("save_turn", user_id, user_text, reply)

    async def clear_history(self, user_id: int) -> None:
        self.local.clear_history(user_id)
        await self._call("clear_history", user_id)

    # profile + xp
    def add_xp(self, user_id: int, username: str | None, amount: int) -> None:
        """Buffered in memory (cheap, sync); flushed periodically by ``flush_xp``."""
        with self._xp_lock:
            self._xp[user_id] += amount
            if username:
                self._names[user_id] = username

    async def flush_xp(self) -> int:
        with self._xp_lock:
            deltas, names = dict(self._xp), dict(self._names)
            self._xp.clear()
        if not deltas:
            return 0
        try:
            await self._call("flush_xp", deltas, names)
        except Exception:  # noqa: BLE001
            logger.exception("XP flush failed; re-queueing")
            with self._xp_lock:
                for uid, amount in deltas.items():
                    self._xp[uid] += amount
        return len(deltas)

    async def get_profile(self, user_id: int) -> dict[str, Any]:
        profile = await self._call("get_profile", user_id) or {"user_id": user_id, "xp": 0, "persona": "default"}
        with self._xp_lock:
            profile = dict(profile)
            profile["xp"] = int(profile.get("xp") or 0) + self._xp.get(user_id, 0)
        profile.setdefault("persona", "default")
        profile["persona"] = profile.get("persona") or "default"
        return profile

    async def set_persona(self, user_id: int, persona: str) -> None:
        await self._call("upsert_profile", user_id, persona=persona)

    async def leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        await self.flush_xp()
        return await self._call("leaderboard", limit)

    # todos / notes / reminders (straight pass-through)
    async def add_todo(self, user_id: int, text: str):
        return await self._call("add_todo", user_id, text)

    async def list_todos(self, user_id: int):
        return await self._call("list_todos", user_id)

    async def set_todo_done(self, user_id: int, todo_id: int, done: bool = True) -> bool:
        return await self._call("set_todo_done", user_id, todo_id, done)

    async def delete_todo(self, user_id: int, todo_id: int) -> bool:
        return await self._call("delete_todo", user_id, todo_id)

    async def clear_done_todos(self, user_id: int) -> int:
        return await self._call("clear_done_todos", user_id)

    async def add_note(self, user_id: int, body: str):
        return await self._call("add_note", user_id, body)

    async def list_notes(self, user_id: int):
        return await self._call("list_notes", user_id)

    async def delete_note(self, user_id: int, note_id: int) -> bool:
        return await self._call("delete_note", user_id, note_id)

    async def add_reminder(self, user_id: int, chat_id: int, text: str, due_ts: float) -> int:
        return await self._call("add_reminder", user_id, chat_id, text, due_ts)

    async def mark_reminder_sent(self, reminder_id: int) -> None:
        await self._call("mark_reminder_sent", reminder_id)

    async def pending_reminders(self):
        return await self._call("pending_reminders")

    async def list_reminders(self, user_id: int):
        return await self._call("list_reminders", user_id)

    async def cancel_reminder(self, user_id: int, reminder_id: int) -> bool:
        return await self._call("cancel_reminder", user_id, reminder_id)


def build_store(url: str | None, key: str | None) -> Store:
    """Create a Store; Supabase is optional so the bot still boots without it."""
    if not (url and key):
        logger.warning("SUPABASE_URL/SUPABASE_KEY not set: history, todos and reminders will not survive restarts")
        return Store(None)
    from supabase import create_client

    return Store(SupabaseBackend(create_client(url, key)))
