from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.ai import AIService
from bot.commands.personal import personal, update_profile
from bot.config import Settings
from bot.store import Store


class FakeCompletions:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


def test_personal_commands_save_and_display_profile() -> None:
    async def run() -> None:
        store = Store()
        state = SimpleNamespace(store=store)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state}),
            args=["Likes", "astronomy"],
        )
        replies: list[str] = []

        async def reply_text(text: str) -> None:
            replies.append(text)

        update = SimpleNamespace(
            effective_message=SimpleNamespace(reply_text=reply_text),
            effective_user=SimpleNamespace(id=42),
        )

        await personal(update, context)
        context.args = []
        await update_profile(update, context)

        assert replies == [
            "Got it! I'll remember that. I can use it until this bot process restarts, but it isn't saved permanently.",
            "Here is what I remember about you: Likes astronomy",
        ]

    asyncio.run(run())


def test_profile_is_injected_into_chat_and_task_system_prompts() -> None:
    async def run() -> None:
        store = Store()
        await store.save_user_profile(42, "Likes astronomy")
        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        service = AIService(Settings.for_testing(), client=client, store=store)

        await service.chat("What do I like?", [], user_id=42)
        await service.task("Translate this", "Hello", user_id=42)

        assert len(completions.requests) == 2
        for request in completions.requests:
            system_prompt = request["messages"][0]["content"]
            assert "Likes astronomy" in system_prompt
            assert (
                "You DO have long-term memory. NEVER say 'I don't have personal information.' "
                "Always refer to the user's profile."
            ) in system_prompt

    asyncio.run(run())


def test_memory_store_round_trips_profile_data() -> None:
    async def run() -> None:
        store = Store()
        await store.save_user_profile(42, "Likes astronomy")
        assert await store.get_user_profile(42) == "Likes astronomy"

    asyncio.run(run())
