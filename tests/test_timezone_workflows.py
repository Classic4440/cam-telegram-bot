from __future__ import annotations

import asyncio
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from telegram.ext import ConversationHandler

from bot.commands.info import _category_commands
from bot.commands.utility import (
    ASK_REMINDER_MESSAGE,
    ASK_REMINDER_TIME,
    _cancel_reminder_conversation,
    _remind_receive_message,
    _remind_receive_time,
    build_reminder_conversation_handler,
    cmd_time,
    cmd_remind,
    handle_timezone_callback,
)
from bot.config import Settings
from bot.registry import discover, visible_commands
from bot.services.timeparse import parse_reminder
from bot.store import Store


def _context(store: Store | None = None) -> SimpleNamespace:
    state = SimpleNamespace(
        store=store or Store(),
        settings=Settings.for_testing(default_timezone="UTC"),
    )
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"state": state}),
        user_data={},
        args=[],
    )


def test_timezone_profile_round_trip_and_callback_saves_selection() -> None:
    async def run() -> None:
        store = Store()
        context = _context(store)
        answer = AsyncMock()
        edit = AsyncMock()
        update = SimpleNamespace(
            callback_query=SimpleNamespace(answer=answer, edit_message_text=edit),
            effective_user=SimpleNamespace(id=42),
        )

        await handle_timezone_callback(
            update,
            context,
            "42:Africa/Kampala",
        )

        answer.assert_awaited_once_with()
        assert (await store.get_profile(42))["timezone"] == "Africa/Kampala"
        assert "Africa/Kampala" in edit.await_args.args[0]

    asyncio.run(run())


def test_timezone_callback_rejects_other_user_and_unknown_zone() -> None:
    async def run() -> None:
        for payload, user_id, expected in (
            ("42:Africa/Kampala", 7, "another user"),
            ("42:Not/AZone", 42, "invalid"),
        ):
            answer = AsyncMock()
            update = SimpleNamespace(
                callback_query=SimpleNamespace(answer=answer, edit_message_text=AsyncMock()),
                effective_user=SimpleNamespace(id=user_id),
            )
            await handle_timezone_callback(update, _context(), payload)
            assert expected in answer.await_args.args[0]

    asyncio.run(run())


def test_saved_timezone_is_stripped_from_reminder_message_and_used_for_clock() -> None:
    due, reminder_text = parse_reminder(
        "10m Africa/Kampala drink water",
        tz_name="UTC",
    )

    assert due.tzinfo == timezone.utc
    assert reminder_text == "drink water"


def test_argument_reminder_uses_saved_timezone_and_removes_zone_token() -> None:
    async def run() -> None:
        store = Store()
        await store.set_timezone(42, "Africa/Kampala")
        context = _context(store)
        jobs: list[dict] = []
        context.args = ["tomorrow", "9am", "Africa/Kampala", "standup"]
        context.job_queue = SimpleNamespace(
            run_once=Mock(side_effect=lambda *_args, **kwargs: jobs.append(kwargs))
        )
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=123),
        )
        with patch("bot.commands.utility.safe_reply", new=AsyncMock()) as reply:
            await cmd_remind(update, context)

        assert len(jobs) == 1
        assert jobs[0]["when"].astimezone(ZoneInfo("Africa/Kampala")).hour == 9
        assert jobs[0]["data"]["message"] == "standup"
        assert "Africa/Kampala" in reply.await_args.args[1]

    asyncio.run(run())


def test_timezone_aware_reminder_conversation_completes_and_schedules() -> None:
    async def run() -> None:
        store = Store()
        await store.set_timezone(42, "Africa/Kampala")
        context = _context(store)
        jobs: list[dict] = []
        context.job_queue = SimpleNamespace(
            run_once=Mock(side_effect=lambda *_args, **kwargs: jobs.append(kwargs))
        )
        time_update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(text="tomorrow 9am"),
            effective_chat=SimpleNamespace(id=123),
        )
        with patch("bot.commands.utility.safe_reply", new=AsyncMock()) as reply:
            state = await _remind_receive_time(time_update, context)
            assert state == ASK_REMINDER_MESSAGE
            assert "What should I remind you" in reply.await_args.args[1]

            message_update = SimpleNamespace(
                effective_user=SimpleNamespace(id=42),
                effective_message=SimpleNamespace(text="drink water"),
                effective_chat=SimpleNamespace(id=123),
            )
            state = await _remind_receive_message(message_update, context)

        assert state == ConversationHandler.END
        assert len(jobs) == 1
        assert jobs[0]["when"].tzinfo == timezone.utc
        assert jobs[0]["when"].astimezone(ZoneInfo("Africa/Kampala")).hour == 9
        assert jobs[0]["data"] == {"chat_id": 123, "message": "drink water"}
        assert "Africa/Kampala" in reply.await_args.args[1]
        assert "reminder_due" not in context.user_data

    asyncio.run(run())


def test_time_command_displays_the_saved_timezone() -> None:
    async def run() -> None:
        store = Store()
        await store.set_timezone(42, "Africa/Kampala")
        context = _context(store)
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
        with patch("bot.commands.utility.safe_reply", new=AsyncMock()) as reply:
            await cmd_time(update, context)

        assert "Africa/Kampala" in reply.await_args.args[1]
        assert "EAT" in reply.await_args.args[1]

    asyncio.run(run())


def test_reminder_conversation_cancel_callback_acknowledges_and_clears_state() -> None:
    async def run() -> None:
        context = _context()
        context.user_data.update(reminder_due=object(), reminder_timezone="UTC")
        answer, edit = AsyncMock(), AsyncMock()
        update = SimpleNamespace(
            callback_query=SimpleNamespace(data="remind:cancel:42", answer=answer, edit_message_text=edit),
            effective_user=SimpleNamespace(id=42),
        )

        result = await _cancel_reminder_conversation(update, context)

        assert result == ConversationHandler.END
        answer.assert_awaited_once_with()
        edit.assert_awaited_once_with("Reminder setup cancelled.")
        assert not context.user_data

    asyncio.run(run())


def test_reminder_conversation_is_registered_and_commands_are_documented() -> None:
    discover()
    handler = build_reminder_conversation_handler()
    assert isinstance(handler, ConversationHandler)
    assert len(handler.entry_points) == 1

    commands = visible_commands(include_admin=True)
    rendered_help = "\n".join(
        command
        for category in ("games", "tools", "ai_media", "settings")
        for command in _category_commands(category)
    )
    assert all(f"/{spec.name}" in rendered_help for spec in commands)
    assert all(spec.description for spec in commands)
    assert "/timezone" in rendered_help
    assert ASK_REMINDER_TIME == 0
