from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import _handle_polling_error, _poll_with_single_conflict_retry
from bot.ai import build_system_prompt
from bot.commands.admin import cmd_myrights
from telegram.error import Conflict


def test_myrights_reports_administrator_permissions() -> None:
    async def run() -> None:
        member = SimpleNamespace(
            status="administrator",
            can_delete_messages=True,
            can_restrict_members=True,
            can_pin_messages=False,
        )
        bot = SimpleNamespace(id=123, get_chat_member=AsyncMock(return_value=member))
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        )
        context = SimpleNamespace(bot=bot)

        with patch("bot.commands.admin.safe_reply", new=AsyncMock()) as reply:
            await cmd_myrights(update, context)

        bot.get_chat_member.assert_awaited_once_with(chat_id=-1001, user_id=123)
        response = reply.await_args.args[1]
        assert "I am an administrator" in response
        assert "Delete messages" in response
        assert "Restrict members" in response
        assert "Pin messages" not in response

    asyncio.run(run())


def test_myrights_reports_non_admin_status_and_skips_private_chats() -> None:
    async def run() -> None:
        bot = SimpleNamespace(
            id=123,
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
        )
        context = SimpleNamespace(bot=bot)
        group_update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-1001, type="group"),
        )

        with patch("bot.commands.admin.safe_reply", new=AsyncMock()) as reply:
            await cmd_myrights(group_update, context)
            assert "not an administrator" in reply.await_args.args[1]

            private_update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=42, type="private"),
            )
            await cmd_myrights(private_update, context)
            assert "group or supergroup" in reply.await_args.args[1]

        bot.get_chat_member.assert_awaited_once_with(chat_id=-1001, user_id=123)

    asyncio.run(run())


def test_ai_prompt_does_not_assume_group_admin_status() -> None:
    prompt = build_system_prompt("default", "chat")

    assert "your actual status and permissions vary by chat" in prompt
    assert "Never assume or claim administrator status without checking" in prompt
    assert "tell the user to run /myrights" in prompt


def test_polling_conflict_requests_clean_shutdown() -> None:
    async def run() -> None:
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        conflict_event = asyncio.Event()

        _handle_polling_error(
            Conflict("terminated by other getUpdates request"),
            loop,
            stop_event,
            conflict_event,
        )
        await asyncio.wait_for(conflict_event.wait(), timeout=1)
        assert not stop_event.is_set()

    asyncio.run(run())


def test_polling_startup_conflict_retries_once_then_shutdown() -> None:
    async def run() -> None:
        class FakeUpdater:
            running = False

            def __init__(self) -> None:
                self.calls = 0

            async def start_polling(self, **_kwargs) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise Conflict("terminated by other getUpdates request")
                stop_event.set()

            async def stop(self) -> None:
                self.running = False

        updater = FakeUpdater()
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        with patch("app._wait_before_polling_retry", new=AsyncMock(return_value=True)) as wait:
            await _poll_with_single_conflict_retry(updater, loop, stop_event)

        assert updater.calls == 2
        wait.assert_awaited_once_with(stop_event)

    asyncio.run(run())
