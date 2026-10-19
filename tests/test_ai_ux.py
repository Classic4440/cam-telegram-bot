from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.ai import ChatResult
from bot.commands.personal import delete_saved_note, list_saved_notes, save_note
from bot.config import Settings
from bot.errors import AIUnavailable
from bot.handlers.message_handler import handle_regenerate_callback, handle_user_text
from bot.registry import discover, visible_commands
from bot.security import TokenBucketLimiter
from bot.store import Store


def _state(ai, *, limiter=None):
    return SimpleNamespace(
        ai=ai,
        store=Store(),
        settings=Settings.for_testing(),
        limiter=limiter or TokenBucketLimiter(10, 2),
        stats=SimpleNamespace(errors=0, messages=0, ai_chats=0),
        user_lock=lambda _user_id: asyncio.Lock(),
    )


def test_ai_reply_offers_regenerate_and_callback_edits_response() -> None:
    async def run() -> None:
        calls: list[str] = []

        class FakeAI:
            async def chat(self, text, history, **_kwargs):
                calls.append(text)
                return ChatResult(
                    text="First answer" if len(calls) == 1 else "Fresh answer",
                    mode="chat",
                    model="test-model",
                )

        state = _state(FakeAI())
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            user_data={},
        )
        reply_calls = []

        async def reply_text(text, **kwargs):
            reply_calls.append((text, kwargs))
            return SimpleNamespace(message_id=876)

        message = SimpleNamespace(text="Tell me something", reply_text=reply_text)
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=SimpleNamespace(id=42),
        )

        await handle_user_text(update, context, message.text)

        keyboard = reply_calls[0][1]["reply_markup"].inline_keyboard
        assert keyboard[0][0].text == "🔄 Regenerate"
        assert keyboard[0][0].callback_data == "regen:42"
        assert context.user_data["ai_regenerate"]["876"]["text"] == message.text

        answer, edit = AsyncMock(), AsyncMock()
        response = SimpleNamespace(message_id=876)
        callback_update = SimpleNamespace(
            callback_query=SimpleNamespace(answer=answer, message=response, edit_message_text=edit),
            effective_user=SimpleNamespace(id=42),
        )
        await handle_regenerate_callback(callback_update, context, "42")

        answer.assert_awaited_once_with("Generating a fresh response…")
        assert edit.await_args.args[0] == "Fresh answer"
        assert edit.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "regen:42"
        assert calls == ["Tell me something", "Tell me something"]
        assert state.stats.ai_chats == 2

    asyncio.run(run())


def test_ai_provider_failure_is_logged_and_returns_friendly_reply() -> None:
    async def run() -> None:
        class BrokenAI:
            async def chat(self, *_args, **_kwargs):
                raise AIUnavailable("provider unavailable")

        state = _state(BrokenAI())
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            user_data={},
        )
        reply = AsyncMock()
        message = SimpleNamespace(text="Hello", reply_text=reply)
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=SimpleNamespace(id=7),
        )

        await handle_user_text(update, context, message.text)

        assert "unavailable right now" in reply.await_args.args[0]
        assert state.stats.errors == 1

    asyncio.run(run())


def test_regenerate_callback_is_user_scoped_and_handles_provider_failure() -> None:
    async def run() -> None:
        class BrokenAI:
            async def chat(self, *_args, **_kwargs):
                raise AIUnavailable("provider unavailable")

        state = _state(BrokenAI())
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            user_data={
                "ai_regenerate": {
                    "876": {"text": "Hello", "history": []},
                }
            },
        )
        answer, edit, reply = AsyncMock(), AsyncMock(), AsyncMock()
        response = SimpleNamespace(message_id=876, reply_text=reply)
        query = SimpleNamespace(answer=answer, message=response, edit_message_text=edit)

        outsider = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=7))
        await handle_regenerate_callback(outsider, context, "42")
        answer.assert_awaited_once_with("This response belongs to another user.", show_alert=True)
        assert not edit.await_count

        answer.reset_mock()
        owner = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=42))
        await handle_regenerate_callback(owner, context, "42")
        answer.assert_awaited_once_with("Generating a fresh response…")
        assert "unavailable right now" in reply.await_args.args[0]
        assert state.stats.errors == 1

    asyncio.run(run())


def test_ai_chat_rate_limit_blocks_provider_call() -> None:
    async def run() -> None:
        class FakeAI:
            chat = AsyncMock()

        state = _state(FakeAI(), limiter=SimpleNamespace(consume=Mock(return_value=3.2)))
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            user_data={},
        )
        reply = AsyncMock()
        message = SimpleNamespace(text="Hello", reply_text=reply)
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=SimpleNamespace(id=7),
        )

        await handle_user_text(update, context, message.text)

        FakeAI.chat.assert_not_awaited()
        assert "wait 4s" in reply.await_args.args[0]

    asyncio.run(run())


def test_saved_note_commands_scope_operations_to_user() -> None:
    async def run() -> None:
        store = Store()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": SimpleNamespace(store=store)}),
            args=["Keep", "this", "private"],
        )
        replies = []

        async def reply_text(text, **_kwargs):
            replies.append(text)

        message = SimpleNamespace(reply_text=reply_text)
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(type="private"),
            effective_user=SimpleNamespace(id=42),
        )
        await save_note(update, context)

        context.args = []
        await list_saved_notes(update, context)
        context.args = ["1"]
        await delete_saved_note(update, context)
        context.args = []
        await list_saved_notes(update, context)

        assert "Saved note #1" in replies[0]
        assert "#1: Keep this private" in replies[1]
        assert "deleted" in replies[2]
        assert "no saved notes" in replies[3]
        assert await store.list_notes(7) == []

    asyncio.run(run())


def test_saved_notes_are_not_created_or_shown_in_group_chats() -> None:
    async def run() -> None:
        store = Store()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": SimpleNamespace(store=store)}),
            args=["sensitive", "note"],
        )
        reply = AsyncMock()
        message = SimpleNamespace(reply_text=reply)
        update = SimpleNamespace(
            effective_message=message,
            effective_chat=SimpleNamespace(type="group"),
            effective_user=SimpleNamespace(id=42),
        )

        await save_note(update, context)
        context.args = []
        await list_saved_notes(update, context)

        assert reply.await_count == 2
        assert all("privacy" in call.args[0] for call in reply.await_args_list)
        assert await store.list_notes(42) == []

    asyncio.run(run())


def test_saved_note_commands_are_listed_for_users() -> None:
    discover()
    names = {command.name for command in visible_commands()}
    assert {"save", "saved", "unsave"} <= names
