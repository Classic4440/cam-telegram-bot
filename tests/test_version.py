from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.ai import build_system_prompt
from bot.commands.version import cmd_version
from bot.registry import REGISTRY
from bot.version import RELEASE_NOTES, __version__


def test_version_and_release_notes_are_in_ai_system_prompt() -> None:
    prompt = build_system_prompt("default", "chat")

    assert f"You are version {__version__}." in prompt
    assert f"Here are your release notes: {RELEASE_NOTES}" in prompt
    assert "If a user asks about your version or what's new, use this information." in prompt


def test_version_command_is_registered_and_returns_release_notes() -> None:
    assert REGISTRY["version"].handler is cmd_version

    async def run() -> None:
        replies: list[str] = []

        async def reply_text(text: str, **kwargs) -> None:
            replies.append(text)

        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text),
        )
        await cmd_version(update, SimpleNamespace())

        assert len(replies) == 1
        assert f"Version {__version__}" in replies[0]
        assert RELEASE_NOTES in replies[0]
        assert "natural-language requests" in RELEASE_NOTES
        assert "Qwen 3.8 27B vision model" in RELEASE_NOTES
        assert "group permission reporting" in RELEASE_NOTES
        assert "timezone preferences" in RELEASE_NOTES
        assert "guided reminder conversation" in RELEASE_NOTES
        assert "AI response regeneration" in RELEASE_NOTES
        assert "private persistent notes" in RELEASE_NOTES

    asyncio.run(run())
