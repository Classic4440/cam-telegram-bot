"""Media handlers: images, audio, voice messages."""
from __future__ import annotations

import asyncio
import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.errors import AIUnavailable
from bot.formatting import reply_html
from bot.handlers.message_handler import handle_user_text
from bot.state import get_state
from bot.utils import (
    MediaError,
    download_file,
    process_image,
)

logger = logging.getLogger(__name__)


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle image messages: resize, analyze, OCR."""
    if not update.message or not update.message.photo:
        return

    try:
        photo = update.message.photo[-1]  # Get highest quality
        await update.message.reply_text("📸 Processing image...")

        # Download image
        local_path = await download_file(context, photo.file_id, "jpg")

        # Process (resize)
        processed_path, original_info = process_image(local_path)

        state = get_state(context)
        text_result, analysis_result = await asyncio.gather(
            state.ai.analyze_image(
                processed_path,
                "Extract all text from this image. If there is no text, say 'No text found'.",
            ),
            state.ai.analyze_image(processed_path, "Describe this image in detail."),
            return_exceptions=True,
        )

        sections: list[tuple[str, str]] = []
        for title, result in (
            ("📝 Text detected", text_result),
            ("🤖 Analysis", analysis_result),
        ):
            if isinstance(result, AIUnavailable):
                state.stats.errors += 1
                content = "Sorry, image processing is unavailable right now. Please try again later."
            elif isinstance(result, Exception):
                raise result
            else:
                content = result
            sections.append((title, content))

        response = (
            f"<b>✅ Image processed</b>\n\n"
            f"📏 Original: {html.escape(original_info)}\n\n"
            + "\n\n".join(
                f"<b>{title}</b>\n{html.escape(content)}"
                for title, content in sections
            )
        )
        await reply_html(update.message, response)

    except MediaError as e:
        await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Image handler failed")
        await update.message.reply_text("❌ Failed to process image")


async def _handle_audio_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: str,
    file_type: str,
) -> None:
    if not update.message:
        return

    try:
        await update.message.reply_text("🎙️ Transcribing audio...")
        local_path = await download_file(context, file_id, file_type)
        state = get_state(context)
        try:
            transcript = await state.ai.transcribe(str(local_path))
        except Exception:
            state.stats.errors += 1
            logger.exception("Audio transcription failed")
            await update.message.reply_text(
                "Sorry, I couldn't transcribe that audio. Please try again or send a text message."
            )
            return

        if not transcript:
            state.stats.errors += 1
            await update.message.reply_text(
                "Sorry, I couldn't detect any speech in that audio. Please try again."
            )
            return

        await handle_user_text(update, context, transcript)
    except MediaError as e:
        await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Audio message handler failed")
        await update.message.reply_text("Sorry, I couldn't process that audio. Please try again.")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe audio files and send their text through the AI chat pipeline."""
    if not update.message or not update.message.audio:
        return

    audio = update.message.audio
    audio_type = audio.mime_type.rsplit("/", 1)[-1] if audio.mime_type else "ogg"
    await _handle_audio_message(update, context, audio.file_id, audio_type)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Transcribe a voice message and send its text through the AI chat pipeline."""
    if not update.message or not update.message.voice:
        return

    await _handle_audio_message(update, context, update.message.voice.file_id, "ogg")
