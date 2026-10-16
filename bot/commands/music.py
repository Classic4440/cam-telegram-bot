"""Music theory commands."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import reply_ai
from bot.registry import command
from bot.services import music as music_service


@command("chord", description="Show the notes in a chord", category="Music", usage="/chord <chord>")
async def chord(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    token = " ".join(context.args).strip()
    if not token:
        await reply_ai(message, "Usage: /chord <chord>\nExamples: /chord C, /chord F#m7")
        return
    try:
        parsed = music_service.parse_chord(token)
    except music_service.MusicError as exc:
        await reply_ai(message, str(exc))
        return
    notes = ", ".join(parsed.notes)
    await reply_ai(message, f"**{parsed.name}**: {notes}")


@command("scale", description="Show the notes in a musical scale", category="Music", usage="/scale <note> [scale]")
async def scale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if not context.args:
        await reply_ai(message, "Usage: /scale <note> [scale]\nExample: /scale D minor")
        return
    root = context.args[0]
    scale_name = " ".join(context.args[1:]) or "major"
    try:
        notes = music_service.scale_notes(root, scale_name)
    except music_service.MusicError as exc:
        await reply_ai(message, str(exc))
        return
    await reply_ai(message, f"**{root} {scale_name}**: {', '.join(notes)}")
