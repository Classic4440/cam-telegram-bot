from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.ai import AIService, build_system_prompt
from bot.commands.admin import cmd_delete
from bot.config import Settings
from bot.errors import AIUnavailable
from bot.handlers.media_handler import handle_image


def test_delete_requires_reply_and_admin_permissions() -> None:
    async def run() -> None:
        bot = SimpleNamespace(
            id=700,
            get_chat_member=AsyncMock(
                side_effect=[
                    SimpleNamespace(status="administrator"),
                    SimpleNamespace(status="administrator", can_delete_messages=True),
                ]
            ),
        )
        target = SimpleNamespace(delete=AsyncMock())
        message = SimpleNamespace(reply_to_message=target)
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(bot=bot)

        with patch("bot.commands.admin.safe_reply", new=AsyncMock()) as reply:
            await cmd_delete(update, context)

        bot.get_chat_member.assert_any_await(-1001, 42)
        bot.get_chat_member.assert_any_await(-1001, 700)
        target.delete.assert_awaited_once()
        assert "Message deleted" in reply.await_args.args[1]

    asyncio.run(run())


def test_delete_rejects_non_admin_users() -> None:
    async def run() -> None:
        bot = SimpleNamespace(
            id=700,
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
        )
        target = SimpleNamespace(delete=AsyncMock())
        update = SimpleNamespace(
            message=SimpleNamespace(reply_to_message=target),
            effective_chat=SimpleNamespace(id=-1001, type="group"),
            effective_user=SimpleNamespace(id=42),
        )

        with patch("bot.commands.admin.safe_reply", new=AsyncMock()) as reply:
            await cmd_delete(update, SimpleNamespace(bot=bot))

        assert "Only group administrators" in reply.await_args.args[1]
        target.delete.assert_not_awaited()
        bot.get_chat_member.assert_awaited_once_with(-1001, 42)

    asyncio.run(run())


def test_ai_image_request_uses_configured_vision_model_and_base64(tmp_path: Path) -> None:
    async def run() -> None:
        image_path = tmp_path / "sample.jpg"
        image_path.write_bytes(b"image-bytes")
        requests: list[dict] = []

        async def create(**request):
            requests.append(request)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="A sample image."))]
            )

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        service = AIService(
            Settings.for_testing(vision_model="vision-model-test"),
            client=client,
        )
        result = await service.analyze_image(image_path, "Describe this image in detail.")

        assert result == "A sample image."
        assert requests[0]["model"] == "vision-model-test"
        content = requests[0]["messages"][0]["content"]
        assert content[0]["text"] == "Describe this image in detail."
        data_url = content[1]["image_url"]["url"]
        assert data_url == "data:image/jpeg;base64," + base64.b64encode(b"image-bytes").decode()

    asyncio.run(run())


def test_image_handler_runs_ocr_and_analysis_and_escapes_html(tmp_path: Path) -> None:
    async def run() -> None:
        processed_image = tmp_path / "processed.jpg"
        processed_image.write_bytes(b"image")
        prompts: list[str] = []

        class FakeAI:
            async def analyze_image(self, _path: Path, prompt: str) -> str:
                prompts.append(prompt)
                if prompt.startswith("Extract"):
                    return "<script>text</script>"
                return "A detailed description."

        state = SimpleNamespace(
            ai=FakeAI(),
            stats=SimpleNamespace(errors=0),
        )
        message = SimpleNamespace(
            photo=[SimpleNamespace(file_id="telegram-photo")],
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state})
        )

        with (
            patch(
                "bot.handlers.media_handler.download_file",
                new=AsyncMock(return_value=tmp_path / "original.jpg"),
            ),
            patch(
                "bot.handlers.media_handler.process_image",
                return_value=(processed_image, "800x600 JPEG"),
            ),
            patch("bot.handlers.media_handler.reply_html", new=AsyncMock()) as formatted_reply,
        ):
            await handle_image(update, context)

        assert prompts == [
            "Extract all text from this image. If there is no text, say 'No text found'.",
            "Describe this image in detail.",
        ]
        html_response = formatted_reply.await_args.args[1]
        assert "&lt;script&gt;text&lt;/script&gt;" in html_response
        assert "<script>" not in html_response
        assert "A detailed description." in html_response

    asyncio.run(run())


def test_image_handler_reports_provider_failure_friendly() -> None:
    async def run() -> None:
        class FakeAI:
            async def analyze_image(self, _path: Path, prompt: str) -> str:
                if prompt.startswith("Extract"):
                    raise AIUnavailable("provider failure")
                return "Image description."

        state = SimpleNamespace(
            ai=FakeAI(),
            stats=SimpleNamespace(errors=0),
        )
        message = SimpleNamespace(
            photo=[SimpleNamespace(file_id="telegram-photo")],
            reply_text=AsyncMock(),
        )
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"state": state})
        )

        with (
            patch(
                "bot.handlers.media_handler.download_file",
                new=AsyncMock(return_value=Path("/tmp/original.jpg")),
            ),
            patch(
                "bot.handlers.media_handler.process_image",
                return_value=(Path("/tmp/processed.jpg"), "800x600 JPEG"),
            ),
            patch("bot.handlers.media_handler.reply_html", new=AsyncMock()) as formatted_reply,
        ):
            await handle_image(update, context)

        assert state.stats.errors == 1
        assert "unavailable right now" in formatted_reply.await_args.args[1]
        assert "Image description." in formatted_reply.await_args.args[1]

    asyncio.run(run())


def test_ai_prompt_routes_telegram_actions_to_commands_without_false_admin_claims() -> None:
    prompt = build_system_prompt("default", "chat")

    assert "You cannot execute Telegram API actions directly through chat" in prompt
    assert "reply to the specific message with `/delete`" in prompt
    assert "Never claim to have deleted a message" in prompt
    assert "your actual status and permissions vary by chat" in prompt
