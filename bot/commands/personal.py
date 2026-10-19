"""Commands for saving and retrieving a user's long-term profile."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import reply
from bot.registry import command
from bot.state import get_state


async def _require_private_chat(update: Update) -> bool:
    chat = getattr(update, "effective_chat", None)
    message = getattr(update, "effective_message", None)
    if chat is not None and chat.type != "private":
        if message is not None:
            await message.reply_text("For privacy, manage saved notes by messaging me directly.")
        return False
    return True


@command(
    "save",
    description="Save a private note for later",
    category="Productivity",
    usage="/save <note>",
)
async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not await _require_private_chat(update):
        return

    text = " ".join(context.args).strip()
    if not text:
        await message.reply_text("Usage: /save <note to keep>")
        return
    if len(text) > 1000:
        await message.reply_text("Please keep saved notes under 1,000 characters.")
        return

    note = await get_state(context).store.add_note(user.id, text)
    await message.reply_text(f"Saved note #{note['id']}. Use /saved to view it.")


@command(
    "saved",
    description="List your saved private notes",
    category="Productivity",
    usage="/saved",
)
async def list_saved_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not await _require_private_chat(update):
        return

    notes = await get_state(context).store.list_notes(user.id)
    if not notes:
        await message.reply_text("You have no saved notes yet. Save one with /save <note>.")
        return
    lines = [f"#{note['id']}: {note['body']}" for note in notes[-10:]]
    await reply(message, "Your saved notes:\n" + "\n".join(lines))


@command(
    "unsave",
    description="Delete one of your saved notes by its ID",
    category="Productivity",
    usage="/unsave <note_id>",
)
async def delete_saved_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    if not await _require_private_chat(update):
        return
    if len(context.args) != 1:
        await message.reply_text("Usage: /unsave <note_id>")
        return
    try:
        note_id = int(context.args[0])
    except ValueError:
        await message.reply_text("Note ID must be a number. Use /saved to see your note IDs.")
        return
    deleted = await get_state(context).store.delete_note(user.id, note_id)
    await message.reply_text(
        "Saved note deleted." if deleted else "I couldn't find that note in your saved notes."
    )


@command(
    "personal",
    description="Save information for the bot to remember about you",
    category="Core",
    usage="/personal <information>",
)
async def personal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    text = " ".join(context.args).strip()
    if not text:
        await message.reply_text("Usage: /personal <information to remember>")
        return

    state = get_state(context)
    await state.store.save_user_profile(user.id, text)
    await message.reply_text("Got it! I'll remember that.")


@command(
    "update",
    description="Show the information the bot remembers about you",
    category="Core",
    usage="/update",
)
async def update_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    state = get_state(context)
    profile_data = await state.store.get_user_profile(user.id)
    if not profile_data:
        profile_data = "No profile details have been saved yet."
    await message.reply_text(f"Here is what I remember about you: {profile_data}")
