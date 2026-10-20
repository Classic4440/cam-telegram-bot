"""Persistence layer.

* ``MemoryBackend``   - process-local fallback (also used by tests).  Data is lost on restart.
* ``SupabaseBackend`` - durable Postgres via Supabase (see ``supabase/migrations/``).
* ``Store``           - async facade. Calls Supabase in a worker thread, classifies database errors,
                        and uses explicitly reported in-memory fallback only for transient outages.

All backend methods are synchronous; the facade owns threading.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import itertools
import json
import logging
import math
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class PersistenceFailure(RuntimeError):
    """A classified error that prevented a remote persistence operation."""

    def __init__(
        self,
        method: str,
        category: str,
        *,
        code: str | None = None,
        fallback_applied: bool = False,
        completed_user_ids: frozenset[int] = frozenset(),
    ) -> None:
        self.method = method
        self.category = category
        self.code = code
        self.fallback_applied = fallback_applied
        self.completed_user_ids = completed_user_ids
        if fallback_applied:
            message = (
                f"Supabase is temporarily unavailable during {method}; this operation was kept "
                "in memory only and may be lost when the bot restarts."
            )
        elif completed_user_ids:
            message = (
                f"Some {method} updates completed before the failure; remaining updates are queued "
                "in memory and may be lost when the bot restarts."
            )
        elif category == "schema":
            message = (
                f"Supabase schema is missing or stale during {method}; the operation was not persisted. "
                "Apply the bot persistence migration and reload the API schema."
            )
        elif category == "permission":
            message = (
                f"Supabase denied {method}; the operation was not persisted. Check the server-side "
                "service_role key and database grants."
            )
        elif category == "transient":
            message = f"Supabase is unavailable during {method}; the operation was not persisted."
        else:
            message = f"Supabase rejected {method}; the operation was not persisted. Check server logs."
        super().__init__(message)


class _XPFlushError(Exception):
    def __init__(self, cause: Exception, completed_user_ids: set[int]) -> None:
        self.original_error = cause
        self.completed_user_ids = frozenset(completed_user_ids)
        super().__init__("XP batch flush failed")


_WRITE_METHODS = frozenset(
    {
        "save_turn",
        "clear_history",
        "upsert_profile",
        "save_user_profile",
        "flush_xp",
        "add_todo",
        "set_todo_done",
        "delete_todo",
        "clear_done_todos",
        "add_note",
        "delete_note",
        "add_reminder",
        "mark_reminder_sent",
        "cancel_reminder",
    }
)
_CODE_RE = re.compile(r"\b(PGRST\d{3}|42501)\b")


def _database_error_details(exc: Exception) -> tuple[str, str | None, int | None]:
    """Classify provider errors without logging response bodies or credentials."""
    source = getattr(exc, "original_error", exc)
    code_value = getattr(source, "code", None)
    code = str(code_value) if code_value is not None else None
    status_value = getattr(source, "status_code", None)
    response = getattr(source, "response", None)
    if status_value is None and response is not None:
        status_value = getattr(response, "status_code", None)
    try:
        status = int(status_value) if status_value is not None else None
    except (TypeError, ValueError):
        status = None

    safe_message = str(getattr(source, "message", "") or source)
    match = _CODE_RE.search(safe_message)
    if code is None and match:
        code = match.group(1)
    message = safe_message.lower()

    if code in {"PGRST202", "PGRST205"} or "schema cache" in message:
        return "schema", code, status
    if code == "42501" or status in {401, 403} or "permission denied" in message:
        return "permission", code, status
    if (
        status in {408, 425, 429}
        or (status is not None and status >= 500)
        or isinstance(source, (TimeoutError, ConnectionError, OSError))
        or type(source).__module__.startswith(("httpx", "httpcore", "requests", "urllib3"))
    ):
        return "transient", code, status
    return "database", code, status


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
        self.user_profiles: dict[int, str] = {}
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

    def get_user_profile(self, user_id: int) -> str:
        with self._lock:
            return self.user_profiles.get(user_id, "")

    def save_user_profile(self, user_id: int, text: str) -> None:
        with self._lock:
            self.user_profiles[user_id] = text

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

    def get_user_profile(self, user_id: int) -> str:
        rows = (
            self._t("user_profiles")
            .select("profile_data")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        profile_data = rows[0].get("profile_data", "") if rows else ""
        return profile_data if isinstance(profile_data, str) else ""

    def save_user_profile(self, user_id: int, text: str) -> None:
        self._t("user_profiles").upsert(
            {"user_id": user_id, "profile_data": text}, on_conflict="user_id"
        ).execute()

    def flush_xp(self, deltas: dict[int, int], names: dict[int, str]) -> None:
        completed_user_ids: set[int] = set()
        for user_id, amount in deltas.items():
            parameters = {
                "p_user_id": user_id,
                "p_username": names.get(user_id),
                "p_amount": amount,
            }
            try:
                self.client.rpc("add_xp", parameters).execute()
            except Exception as exc:  # noqa: BLE001 - retain acknowledgment of prior per-user RPCs
                raise _XPFlushError(exc, completed_user_ids) from exc
            completed_user_ids.add(user_id)

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
            logger.error(
                "Supabase circuit opened for %.0fs; persistence operations will use guarded fallback",
                self.cooldown,
            )


class Store:
    """Async facade over a remote backend with an in-memory safety net."""

    def __init__(self, remote: SupabaseBackend | None = None) -> None:
        self.remote = remote
        self.local = MemoryBackend()
        self._breaker = _Breaker()
        self._configuration_failure: tuple[str, str | None] | None = None
        self._last_transient_failure: tuple[str | None, int | None] | None = None
        self._xp: dict[int, int] = defaultdict(int)
        self._names: dict[int, str] = {}
        self._xp_lock = threading.Lock()

    @property
    def durable(self) -> bool:
        return (
            self.remote is not None
            and self._configuration_failure is None
            and self._last_transient_failure is None
            and self._breaker.allow()
        )

    def _raise_persistent_failure(
        self,
        method: str,
        completed_user_ids: frozenset[int] = frozenset(),
    ) -> None:
        if self._configuration_failure is not None:
            category, code = self._configuration_failure
            raise PersistenceFailure(
                method,
                category,
                code=code,
                completed_user_ids=completed_user_ids,
            )
        if self._last_transient_failure is not None:
            code, _status = self._last_transient_failure
            raise PersistenceFailure(
                method,
                "transient",
                code=code,
                fallback_applied=method in _WRITE_METHODS and method != "flush_xp",
                completed_user_ids=completed_user_ids,
            )

    def _fallback(
        self,
        method: str,
        *args: Any,
        completed_user_ids: frozenset[int] = frozenset(),
        **kwargs: Any,
    ) -> Any:
        if method in _WRITE_METHODS:
            logger.warning(
                "Supabase write %s cannot be persisted; applying guarded in-memory fallback",
                method,
            )
            if method != "flush_xp":
                getattr(self.local, method)(*args, **kwargs)
            self._raise_persistent_failure(method, completed_user_ids)
        logger.warning(
            "Supabase read %s is using in-memory fallback; returned data may be stale",
            method,
        )
        return getattr(self.local, method)(*args, **kwargs)

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self.remote is None:
            return getattr(self.local, method)(*args, **kwargs)
        if self._configuration_failure is not None:
            self._raise_persistent_failure(method)
        if not self._breaker.allow():
            return self._fallback(method, *args, **kwargs)

        try:
            result = await asyncio.to_thread(getattr(self.remote, method), *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - provider exception types vary by SDK version
            category, code, status = _database_error_details(exc)
            exception_type = type(getattr(exc, "original_error", exc)).__name__
            completed_user_ids = getattr(exc, "completed_user_ids", frozenset())
            logger.error(
                "Supabase %s failure in %s (code=%s, status=%s, exception=%s)",
                category,
                method,
                code or "unknown",
                status if status is not None else "unknown",
                exception_type,
            )
            if category in {"schema", "permission"}:
                self._configuration_failure = (category, code)
                self._raise_persistent_failure(method, completed_user_ids)

            if category == "transient":
                self._last_transient_failure = (code, status)
                self._breaker.fail()
                return self._fallback(
                    method,
                    *args,
                    completed_user_ids=completed_user_ids,
                    **kwargs,
                )
            raise PersistenceFailure(
                method,
                category,
                code=code,
                completed_user_ids=completed_user_ids,
            ) from exc

        self._breaker.ok()
        self._last_transient_failure = None
        return result

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
        except PersistenceFailure as exc:
            remaining = 0
            with self._xp_lock:
                for uid, amount in deltas.items():
                    if uid not in exc.completed_user_ids:
                        self._xp[uid] += amount
                        remaining += 1
            logger.error(
                "%s; %s users' XP deltas remain queued in memory",
                exc,
                remaining,
            )
            return len(exc.completed_user_ids)
        return len(deltas)

    async def get_profile(self, user_id: int) -> dict[str, Any]:
        profile = await self._call("get_profile", user_id) or {"user_id": user_id, "xp": 0, "persona": "default"}
        with self._xp_lock:
            profile = dict(profile)
            profile["xp"] = int(profile.get("xp") or 0) + self._xp.get(user_id, 0)
        profile.setdefault("persona", "default")
        profile["persona"] = profile.get("persona") or "default"
        return profile

    async def set_timezone(self, user_id: int, timezone_name: str) -> None:
        """Persist the user's IANA timezone in their profile."""
        await self._call("upsert_profile", user_id, timezone=timezone_name)

    async def get_user_profile(self, user_id: int) -> str:
        return await self._call("get_user_profile", user_id)

    async def save_user_profile(self, user_id: int, text: str) -> None:
        await self._call("save_user_profile", user_id, text)

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
    """Create the store, rejecting known public Supabase keys for this private server app."""
    if not url and not key:
        logger.warning(
            "Supabase is not configured; persistence writes are process-local and may be lost on restart"
        )
        return Store(None)
    if not url or not key:
        raise RuntimeError("Set both SUPABASE_URL and SUPABASE_KEY to enable Supabase persistence.")

    key_kind = _supabase_key_kind(key)
    if key_kind == "public":
        raise RuntimeError(
            "SUPABASE_KEY is a public/anon key. Configure a server-side Supabase service_role secret "
            "in Render; public keys are not accepted for this private bot."
        )
    if key_kind == "unknown":
        logger.warning(
            "Supabase key role could not be identified; verify SUPABASE_KEY is a server-side service_role secret"
        )
    host = urlparse(url).hostname or "<invalid-host>"
    logger.info("Supabase configuration present (host=%s, key_kind=%s)", host, key_kind)

    from supabase import create_client

    return Store(SupabaseBackend(create_client(url, key)))


def _supabase_key_kind(key: str) -> str:
    """Return only a safe key classification; never return or log the key itself."""
    if key.startswith("sb_secret_"):
        return "server-secret"
    if key.startswith("sb_publishable_"):
        return "public"
    parts = key.split(".")
    if len(parts) != 3:
        return "unknown"
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return "unknown"
    role = claims.get("role") if isinstance(claims, dict) else None
    if role == "service_role":
        return "service-role"
    if role in {"anon", "authenticated"}:
        return "public"
    return "unknown"
