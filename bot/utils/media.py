"""Media handling: download, transcribe, TTS, image processing."""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

from PIL import Image
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(__file__).parent.parent / "media"
MEDIA_DIR.mkdir(exist_ok=True)

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "flac"}
ALLOWED_IMAGE = {"jpg", "jpeg", "png", "webp", "bmp"}


class MediaError(ValueError):
    pass


async def download_file(context: ContextTypes.DEFAULT_TYPE, file_id: str, file_type: str) -> Path:
    """Download file from Telegram, return local path."""
    try:
        file = await context.bot.get_file(file_id)
        if file.file_size and file.file_size > MAX_FILE_SIZE:
            raise MediaError(f"File too large ({file.file_size} bytes, max {MAX_FILE_SIZE})")

        ext = file_type.lower()
        local_path = MEDIA_DIR / f"{file_id}.{ext}"
        output = io.BytesIO()
        await file.download_to_memory(output)
        local_path.write_bytes(output.getvalue())

        logger.info(f"Downloaded {file_type} file: {local_path}")
        return local_path
    except Exception as e:
        raise MediaError(f"Failed to download file: {e}") from None


async def text_to_speech(text: str, api_key: str | None = None) -> Path | None:
    """Convert text to speech, return audio file path."""
    if not api_key:
        logger.warning("No API key for TTS")
        return None

    try:
        # Placeholder - implement with Elevenlabs, Google TTS, or similar
        logger.info(f"Converting to speech: {text[:50]}...")
        return None
    except Exception as e:
        logger.exception(f"TTS failed: {e}")
        return None


def process_image(file_path: Path, max_width: int = 1024) -> tuple[Path, str]:
    """Resize image, return new path and format info."""
    try:
        img = Image.open(file_path)
        original_format = f"{img.size[0]}x{img.size[1]} {img.format}"

        if img.size[0] > max_width:
            ratio = max_width / img.size[0]
            new_size = (max_width, int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        output_path = file_path.with_stem(file_path.stem + "_processed")
        img.save(output_path, format="JPEG", quality=85)

        logger.info(f"Processed image: {file_path} -> {output_path}")
        return output_path, original_format
    except Exception as e:
        logger.exception(f"Image processing failed: {e}")
        raise MediaError(f"Failed to process image: {e}") from None
