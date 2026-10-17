from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.commands.admin import cmd_admin, is_admin
from bot.commands.games import cmd_guess, cmd_hangman, cmd_tictactoe
from bot.commands.utility import _send_reminder, cmd_remind
from bot.config import Settings
from bot.content import ContentLibrary
from bot.handlers.message_handler import handle_user_text
from bot.services.gamelogic import Hangman

def test_generated_content_loads_and_has_more_than_fifty_jokes() -> None:
    content = ContentLibrary()
    jokes = content.get_all("jokes")

    assert len(jokes) > 50
    assert len(jokes) == 94
    assert content.total() == 317


def test_full_content_pipeline_is_reproducible_and_writes_all_eight_packs(tmp_path: Path) -> None:
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_content.py"),
                "--all",
                "--out",
                str(output),
                "--seed",
                "20261015",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    first_files = sorted(outputs[0].glob("*.generated.json"))
    second_files = sorted(outputs[1].glob("*.generated.json"))
    assert len(first_files) == len(second_files) == 8
    assert sum(
        len(entries)
        for path in first_files
        for entries in json.loads(path.read_text(encoding="utf-8")).values()
    ) == 317
    assert [path.read_bytes() for path in first_files] == [path.read_bytes() for path in second_files]


def test_admin_ids_are_parsed_and_admin_panel_uses_configured_settings(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:TEST-TOKEN")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_IDS", "42; 73, 99")
    settings = Settings.from_env()
    context = SimpleNamespace(
        bot_data={"state": SimpleNamespace(settings=settings)}
    )

    assert settings.admin_ids == frozenset({42, 73, 99})
    assert is_admin(42, context)
    assert not is_admin(100, context)

    async def run() -> None:
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
        with patch("bot.commands.admin.safe_reply", new=AsyncMock()) as reply:
            await cmd_admin(update, context)
        assert "Admin Panel" in reply.await_args.args[1]

    asyncio.run(run())


def test_remind_schedules_job_queue_callback() -> None:
    async def run() -> None:
        jobs: list[tuple[tuple, dict]] = []
        job_queue = SimpleNamespace(
            run_once=Mock(side_effect=lambda *args, **kwargs: jobs.append((args, kwargs)))
        )
        context = SimpleNamespace(args=["10m", "drink", "water"], job_queue=job_queue)
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=123))

        with patch("bot.commands.utility.safe_reply", new=AsyncMock()) as reply:
            await cmd_remind(update, context)

        assert len(jobs) == 1
        callback, = jobs[0][0]
        options = jobs[0][1]
        assert callback is _send_reminder
        assert options["when"].tzinfo == timezone.utc
        assert options["data"] == {"chat_id": 123, "message": "drink water"}
        assert "Reminder set" in reply.await_args.args[1]

        bot = SimpleNamespace(send_message=AsyncMock())
        job = SimpleNamespace(data=options["data"])
        await _send_reminder(SimpleNamespace(job=job, bot=bot))
        bot.send_message.assert_awaited_once_with(chat_id=123, text="⏰ Reminder: drink water")

    asyncio.run(run())


def test_tictactoe_state_survives_moves_sent_as_messages() -> None:
    async def run() -> None:
        context = SimpleNamespace(user_data={}, bot_data={})
        message = SimpleNamespace(text="1")
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))

        with patch("bot.commands.games.safe_reply", new=AsyncMock()):
            await cmd_tictactoe(update, context)
            assert context.user_data["tictactoe"] == [""] * 9
            await handle_user_text(update, context, "1")
            board = context.user_data["tictactoe"]
            assert board[0] == "X"
            assert board.count("O") == 1
            await handle_user_text(update, context, "1")

        assert context.user_data["tictactoe"] is board

    asyncio.run(run())


def test_hangman_state_is_kept_for_follow_up_guesses() -> None:
    async def run() -> None:
        content = SimpleNamespace(get_all=lambda _kind: ["apple"])
        context = SimpleNamespace(user_data={}, bot_data={"content_lib": content}, args=["a"])
        update = SimpleNamespace(message=SimpleNamespace(text="a"))

        with patch("bot.commands.games.safe_reply", new=AsyncMock()):
            await cmd_hangman(update, context)
            game = context.user_data["hangman"]
            assert isinstance(game, Hangman)
            await cmd_guess(update, context)

        assert context.user_data["hangman"] is game
        assert game.guessed == {"a"}
