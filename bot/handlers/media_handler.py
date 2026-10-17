"""Media handlers: images, audio, voice messages."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.message_handler import handle_user_text
from bot.state import get_state
from bot.utils import (
    MediaError,
    analyze_image,
    download_file,
    extract_text_from_image,
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

        # Extract text (OCR)
        text_content = extract_text_from_image(processed_path)

        # Analyze with vision API
        config = context.bot_data.get("config") if context.bot_data else None
        ai_key = config.ai_api_key if config else None
        analysis = await analyze_image(processed_path, ai_key)

        response = f"✅ Image processed!\n\n📏 Original: {original_info}\n\n📝 Text detected:\n{text_content}\n\n🤖 Analysis:\n{analysis}"
        await update.message.reply_text(response)

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
