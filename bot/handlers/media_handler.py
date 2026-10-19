"""Media handlers: images, audio, voice messages."""
from __future__ import annotations

import asyncio
import html
import logging
from html.parser import HTMLParser

from telegram import Update
from telegram.ext import ContextTypes

from bot.errors import AIUnavailable
from bot.formatting import markdown_to_html, reply_html
from bot.handlers.message_handler import handle_user_text
from bot.state import get_state
from bot.utils import (
    MediaError,
    download_file,
    process_image,
)

logger = logging.getLogger(__name__)

OCR_PROMPT = (
    "You are an expert OCR assistant. Extract all text from this image. You must preserve the layout, "
    "spacing, and line breaks exactly as they appear. Use Markdown to format headings or separate "
    "sections. Do NOT include any of your own commentary, just the extracted text."
)
ANALYSIS_PROMPT = (
    "Describe this image clearly and concisely using Telegram-compatible HTML. Use bullet points for key "
    "elements. Do not repeat the raw text extraction, just describe what is happening in the image."
)
_TELEGRAM_HTML_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre",
}


class _TelegramHTMLSanitizer(HTMLParser):
    """Keep only Telegram-supported formatting tags from vision model output."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._blocked_depth = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._blocked_depth += 1
            return
        if self._blocked_depth:
            return
        if tag in _TELEGRAM_HTML_TAGS:
            self.parts.append(f"<{tag}>")
        elif tag in {"br", "p", "div"}:
            self.parts.append("\n")
        elif tag in {"li"}:
            self.parts.append("\n• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._blocked_depth = max(0, self._blocked_depth - 1)
            return
        if self._blocked_depth:
            return
        if tag in _TELEGRAM_HTML_TAGS:
            self.parts.append(f"</{tag}>")
        elif tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self.parts.append(html.escape(data))


def _format_vision_html(text: str) -> str:
    sanitizer = _TelegramHTMLSanitizer()
    sanitizer.feed(text)
    sanitizer.close()
    return "".join(sanitizer.parts).strip()


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
                OCR_PROMPT,
            ),
            state.ai.analyze_image(processed_path, ANALYSIS_PROMPT),
            return_exceptions=True,
        )

        sections: list[tuple[str, str]] = []
        for title, result in (
            ("📝 Text detected", text_result),
            ("🤖 Analysis", analysis_result),
        ):
            if isinstance(result, AIUnavailable):
                state.stats.errors += 1
                content = "Sorry, I couldn't analyze this part of the image. Please try again later."
            elif isinstance(result, Exception):
                raise result
            else:
                content = result
            sections.append((title, content))

        response = (
            f"<b>✅ Image processed</b>\n\n"
            f"📏 Original: {html.escape(original_info)}\n\n"
            + f"<b>{sections[0][0]}</b>\n{markdown_to_html(sections[0][1])}\n\n"
            + f"<b>{sections[1][0]}</b>\n{_format_vision_html(sections[1][1])}"
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
