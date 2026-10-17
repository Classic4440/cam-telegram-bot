"""Media handlers: images, audio, voice messages."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.utils import (
    MediaError,
    analyze_image,
    download_file,
    extract_text_from_image,
    process_image,
    text_to_speech,
    transcribe_audio,
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
        local_path = await download_file(update, photo.file_id, "jpg")

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


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle audio file messages: transcribe."""
    if not update.message or not update.message.audio:
        return

    try:
        audio = update.message.audio
        await update.message.reply_text("🎵 Transcribing audio...")

        # Download audio
        audio_type = audio.mime_type.rsplit("/", 1)[-1] if audio.mime_type else "ogg"
        local_path = await download_file(update, audio.file_id, audio_type)

        # Transcribe
        config = context.bot_data.get("config") if context.bot_data else None
        ai_key = config.ai_api_key if config else None
        transcript = await transcribe_audio(local_path, ai_key)

        response = f"🎤 Transcript:\n{transcript}"
        await update.message.reply_text(response)

    except MediaError as e:
        await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Audio handler failed")
        await update.message.reply_text("❌ Failed to transcribe audio")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice message: transcribe to text, optionally reply with voice."""
    if not update.message or not update.message.voice:
        return

    try:
        voice = update.message.voice
        await update.message.reply_text("🎙️ Processing voice message...")

        # Download voice
        local_path = await download_file(update, voice.file_id, "ogg")

        # Transcribe
        config = context.bot_data.get("config") if context.bot_data else None
        ai_key = config.ai_api_key if config else None
        transcript = await transcribe_audio(local_path, ai_key)

        # Send text response
        await update.message.reply_text(f"✅ You said:\n{transcript}")

        # Optionally reply with voice (TTS)
        reply_text = f"Got it! You said {transcript[:30]}..."
        voice_path = await text_to_speech(reply_text, ai_key)
        if voice_path:
            await update.message.reply_voice(voice=open(voice_path, "rb"))

    except MediaError as e:
        await update.message.reply_text(f"❌ Error: {e}")
    except Exception as e:
        logger.exception("Voice handler failed")
        await update.message.reply_text("❌ Failed to process voice")
