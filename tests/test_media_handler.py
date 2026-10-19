from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.ai import AIService, ChatResult
from bot.config import Settings
from bot.handlers.media_handler import handle_voice
from bot.security import TokenBucketLimiter
from bot.store import Store


def test_ai_service_transcribes_with_configured_whisper_model(tmp_path: Path) -> None:
    async def run() -> None:
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio data")
        requests: list[dict] = []

        async def create(**request):
            requests.append(request)
            assert request["file"].read() == b"audio data"
            return SimpleNamespace(text=" Turn left at the next street. ")

        client = SimpleNamespace(
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create))
        )
        settings = Settings.for_testing(whisper_model="whisper-large-v3")
        service = AIService(settings, client=client)

        transcript = await service.transcribe(str(audio_path))

        assert transcript == "Turn left at the next street."
        assert requests[0]["model"] == "whisper-large-v3"

    asyncio.run(run())


def test_voice_transcript_uses_chat_pipeline_and_memory(tmp_path: Path) -> None:
    async def run() -> None:
        audio_path = tmp_path / "voice.ogg"
        audio_path.write_bytes(b"audio data")
        store = Store()
        calls: list[str] = []

        class FakeAI:
            async def transcribe(self, path: str) -> str:
                assert path == str(audio_path)
                return "What is the weather like?"

            async def chat(self, text, history, **kwargs) -> ChatResult:
                calls.append(text)
                return ChatResult(text="I can help with the weather.", mode="chat", model="test")

        state = SimpleNamespace(
            settings=Settings.for_testing(),
            store=store,
            ai=FakeAI(),
            stats=SimpleNamespace(errors=0, messages=0, ai_chats=0),
            user_lock=lambda _user_id: asyncio.Lock(),
            limiter=TokenBucketLimiter(10, 2),
        )
        replies: list[str] = []

        async def reply_text(text: str, **_kwargs) -> None:
            replies.append(text)

        message = SimpleNamespace(
            voice=SimpleNamespace(file_id="telegram-file-id"),
            reply_text=reply_text,
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"state": state}))

        with patch(
            "bot.handlers.media_handler.download_file",
            new=AsyncMock(return_value=audio_path),
        ):
            await handle_voice(update, context)

        assert calls == ["What is the weather like?"]
        history = await store.load_history(42, 10)
        assert history[-2:] == [
            {"role": "user", "content": "What is the weather like?"},
            {"role": "assistant", "content": "I can help with the weather."},
        ]
        assert state.stats.ai_chats == 1
        assert any("I can help with the weather." in reply for reply in replies)

    asyncio.run(run())


def test_voice_transcription_failure_replies_without_chat() -> None:
    async def run() -> None:
        class FakeAI:
            async def transcribe(self, _path: str) -> str:
                raise RuntimeError("transcription unavailable")

        state = SimpleNamespace(
            ai=FakeAI(),
            stats=SimpleNamespace(errors=0),
            limiter=TokenBucketLimiter(10, 2),
        )
        replies: list[str] = []

        async def reply_text(text: str, **_kwargs) -> None:
            replies.append(text)

        message = SimpleNamespace(
            voice=SimpleNamespace(file_id="telegram-file-id"),
            reply_text=reply_text,
        )
        update = SimpleNamespace(
            message=message,
            effective_message=message,
            effective_user=SimpleNamespace(id=42),
        )
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"state": state}))

        with patch(
            "bot.handlers.media_handler.download_file",
            new=AsyncMock(return_value=Path("/tmp/voice.ogg")),
        ):
            await handle_voice(update, context)

        assert state.stats.errors == 1
        assert any("couldn't transcribe" in reply for reply in replies)

    asyncio.run(run())
