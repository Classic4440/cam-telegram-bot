"""Commands for saving and retrieving a user's long-term profile."""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from bot.registry import command
from bot.state import get_state


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
    await asyncio.to_thread(state.store.save_user_profile, user.id, text)
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
    profile_data = await asyncio.to_thread(state.store.get_user_profile, user.id)
    if not profile_data:
        profile_data = "No profile details have been saved yet."
    await message.reply_text(f"Here is what I remember about you: {profile_data}")
