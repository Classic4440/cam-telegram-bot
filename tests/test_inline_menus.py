from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram.ext import CallbackQueryHandler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.commands.games import cmd_game, handle_game_callback
from bot.commands.info import cmd_help, cmd_start, handle_help_callback, handle_start_callback
from bot.formatting import html_footer, html_heading, present_message
from bot.registry import CALLBACKS, build_handlers, discover, dispatch_callback


def _context(user_id: int = 42) -> SimpleNamespace:
    return SimpleNamespace(
        user_data={},
        bot_data={
            "state": SimpleNamespace(
                limiter=SimpleNamespace(consume=Mock(return_value=0)),
                stats=SimpleNamespace(callbacks=0, errors=0),
            ),
            "content_lib": SimpleNamespace(get_all=lambda _kind: ["apple"]),
        },
        args=[],
    )


def _callback_update(data: str, *, user_id: int = 42) -> tuple[SimpleNamespace, AsyncMock, AsyncMock]:
    answer = AsyncMock()
    edit = AsyncMock()
    query = SimpleNamespace(
        data=data,
        answer=answer,
        edit_message_text=edit,
    )
    update = SimpleNamespace(
        callback_query=query,
        effective_user=SimpleNamespace(id=user_id),
    )
    return update, answer, edit


def test_game_menu_has_requested_games_and_back_navigation() -> None:
    async def run() -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(),
        )
        context = _context()
        context.args = []

        with patch("bot.commands.games.reply_html", new=AsyncMock()) as reply:
            await cmd_game(update, context)

        keyboard = reply.await_args.kwargs["reply_markup"].inline_keyboard
        assert [row[0].text for row in keyboard] == [
            "Rock Paper Scissors",
            "Hangman",
            "Tic-Tac-Toe",
            "⬅️ Back",
        ]
        assert all(button[0].callback_data.startswith(("game:42:", "start:42:")) for button in keyboard)

    asyncio.run(run())


def test_legacy_game_rps_argument_still_starts_game() -> None:
    async def run() -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(),
        )
        context = _context()
        context.args = ["rps"]

        with patch("bot.commands.games.safe_reply", new=AsyncMock()) as reply:
            await cmd_game(update, context)

        keyboard = reply.await_args.kwargs["reply_markup"].inline_keyboard
        assert [button.text for button in keyboard[0]] == ["Rock", "Paper", "Scissors"]

    asyncio.run(run())


def test_ttt_callback_answers_and_edits_menu_to_active_game() -> None:
    async def run() -> None:
        update, answer, edit = _callback_update("game:42:select:ttt")
        context = _context()

        await handle_game_callback(update, context, "42:select:ttt")

        answer.assert_not_awaited()
        assert context.user_data["tictactoe"] == [""] * 9
        edit.assert_awaited_once()
        assert edit.await_args.kwargs["reply_markup"] is not None
        assert "Tic-Tac-Toe" in edit.await_args.args[0]

    asyncio.run(run())


def test_stale_and_other_users_game_callbacks_are_safe() -> None:
    async def run() -> None:
        update, answer, edit = _callback_update("game:42:stale:unknown")
        await handle_game_callback(update, _context(), "bad")
        answer.assert_not_awaited()
        assert edit.await_args.args[0].find("expired") >= 0

        update, answer, edit = _callback_update("game:42:select:ttt", user_id=7)
        await handle_game_callback(update, _context(user_id=7), "42:select:ttt")
        answer.assert_not_awaited()
        edit.assert_not_awaited()

    asyncio.run(run())


def test_help_command_shows_categories_and_callback_edits_to_category() -> None:
    async def run() -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(),
        )
        context = _context()
        with patch("bot.commands.info.reply_html", new=AsyncMock()) as reply:
            await cmd_help(update, context)

        keyboard = reply.await_args.kwargs["reply_markup"].inline_keyboard
        assert [row[0].text for row in keyboard] == [
            "🎮 Games",
            "🛠️ Tools",
            "🤖 AI & Media",
            "⚙️ Settings",
        ]

        discover()
        callback_update, answer, edit = _callback_update("help:42:category:games")
        await handle_help_callback(callback_update, context, "42:category:games")

        answer.assert_not_awaited()
        edit.assert_awaited_once()
        assert "/tictactoe" in edit.await_args.args[0]
        assert edit.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "⬅️ Back"

    asyncio.run(run())


def test_help_callback_back_and_stale_payload_acknowledged() -> None:
    async def run() -> None:
        context = _context()
        update, answer, edit = _callback_update("help:42:back")
        await handle_help_callback(update, context, "42:back")
        answer.assert_not_awaited()
        assert edit.await_args.kwargs["reply_markup"] is not None

        update, answer, edit = _callback_update("help:42:category:obsolete")
        await handle_help_callback(update, context, "42:category:obsolete")
        answer.assert_not_awaited()
        assert "expired" in edit.await_args.args[0]

    asyncio.run(run())


def test_start_menu_buttons_and_navigation_edit_message() -> None:
    async def run() -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(),
        )
        with patch("bot.commands.info.reply_html", new=AsyncMock()) as reply:
            await cmd_start(update, _context())

        buttons = reply.await_args.kwargs["reply_markup"].inline_keyboard
        assert [row[0].text for row in buttons] == ["🎮 Games", "📚 Commands & help"]

        update, answer, edit = _callback_update("start:42:games")
        await handle_start_callback(update, _context(), "42:games")
        answer.assert_not_awaited()
        assert edit.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "Rock Paper Scissors"

        update, answer, edit = _callback_update("start:42:home")
        await handle_start_callback(update, _context(), "42:home")
        answer.assert_not_awaited()
        assert edit.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "🎮 Games"

        update, answer, edit = _callback_update("start:42:help")
        await handle_start_callback(update, _context(), "42:help")
        answer.assert_not_awaited()
        assert edit.await_args.kwargs["reply_markup"].inline_keyboard[0][0].text == "🎮 Games"

    asyncio.run(run())


def test_presentation_helpers_escape_headings_footers_and_format_body() -> None:
    assert html_heading("<Hello>") == "<b>&lt;Hello&gt;</b>"
    assert html_footer("Use <Back>") == "<i>Use &lt;Back&gt;</i>"
    message = present_message("<Title>", "## Section\n\n- First item", "Footer")
    assert message.startswith("<b>&lt;Title&gt;</b>")
    assert "<b>Section</b>" in message
    assert "• First item" in message
    assert message.endswith("<i>Footer</i>")


def test_registry_installs_callback_query_handler() -> None:
    discover()
    handlers = build_handlers()
    assert any(isinstance(handler, CallbackQueryHandler) for handler in handlers)


def test_dispatcher_answers_before_routing_menu_callback() -> None:
    async def run() -> None:
        discover()
        order = []
        answer = AsyncMock(side_effect=lambda: order.append("answer"))
        edit = AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("edit"))
        query = SimpleNamespace(
            data="help:42:category:games",
            answer=answer,
            edit_message_text=edit,
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
        )
        state = SimpleNamespace(
            limiter=SimpleNamespace(consume=Mock(return_value=0)),
            stats=SimpleNamespace(callbacks=0, errors=0),
        )
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            user_data={},
        )

        await dispatch_callback(update, context)

        answer.assert_awaited_once_with()
        assert order[0] == "answer"
        assert order[1] == "edit"
        assert state.stats.callbacks == 1

    asyncio.run(run())


def test_dispatcher_logs_callback_error_and_attempts_alert_ack(caplog) -> None:
    async def run() -> None:
        prefix = "test_failure_callback"

        async def fail(_update, _context, _payload):
            raise RuntimeError("database callback failure")

        CALLBACKS[prefix] = fail
        answer = AsyncMock()
        query = SimpleNamespace(data=f"{prefix}:test", answer=answer)
        update = SimpleNamespace(
            callback_query=query,
            effective_user=SimpleNamespace(id=42),
        )
        state = SimpleNamespace(
            limiter=SimpleNamespace(consume=Mock(return_value=0)),
            stats=SimpleNamespace(callbacks=0, errors=0),
        )
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
        )
        try:
            await dispatch_callback(update, context)
        finally:
            CALLBACKS.pop(prefix)

        assert answer.await_args_list[0].args == ()
        assert answer.await_args_list[0].kwargs == {}
        assert answer.await_args_list[1].kwargs == {
            "text": "An error occurred.",
            "show_alert": True,
        }
        assert state.stats.errors == 1

    asyncio.run(run())
    assert "database callback failure" in caplog.text
