"""General message handler with AI routing."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.errors import AIUnavailable
from bot.formatting import reply_ai
from bot.registry import command_summary
from bot.security import sanitize_text
from bot.state import get_state

logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command text messages with AI."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if user is None:
        return

    state = get_state(context)
    text = sanitize_text(update.message.text, state.settings.max_input_chars)
    if not text:
        return
    if len(update.message.text) > state.settings.max_input_chars:
        await reply_ai(
            update.message,
            f"Please keep messages under {state.settings.max_input_chars} characters.",
        )
        return

    try:
        async with state.user_lock(user.id):
            history = await state.store.load_history(user.id, state.settings.history_messages)
            result = await state.ai.chat(
                text,
                history,
                user_id=user.id,
                commands=command_summary(),
            )
            await state.store.save_turn(user.id, text, result.text)
            state.stats.messages += 1
            state.stats.ai_chats += 1
        await reply_ai(update.message, result.text)
    except AIUnavailable:
        logger.warning("AI is unavailable for user %s", user.id)
        await reply_ai(update.message, "The AI is unavailable right now. Please try again shortly.")
    except Exception:
        state.stats.errors += 1
        logger.exception("Message handler failed")
        await reply_ai(update.message, "I couldn't process that message. Please try again.")
