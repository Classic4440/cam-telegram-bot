"""General message handler with AI routing."""
from __future__ import annotations

import logging
import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from bot.ai import trim_history
from bot.commands.admin import handle_natural_delete_request, is_natural_delete_request
from bot.commands.games import handle_game_text
from bot.errors import AIUnavailable
from bot.formatting import markdown_to_html, reply_ai
from bot.registry import callback
from bot.registry import command_summary
from bot.security import sanitize_text
from bot.state import get_state

logger = logging.getLogger(__name__)


def _regenerate_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen:{user_id}")]]
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command text messages with AI."""
    if not update.message or not update.message.text:
        return

    await handle_user_text(update, context, update.message.text)


async def handle_user_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    """Send text through the standard AI chat and memory pipeline."""
    if not update.message:
        return
    if await handle_game_text(update, context, text):
        return

    user = update.effective_user
    if user is None:
        return

    state = get_state(context)
    sanitized_text = sanitize_text(text, state.settings.max_input_chars)
    if not sanitized_text:
        return
    if len(text) > state.settings.max_input_chars:
        await reply_ai(
            update.message,
            f"Please keep messages under {state.settings.max_input_chars} characters.",
        )
        return

    wait = state.limiter.consume(user.id)
    if wait > 0:
        await reply_ai(
            update.message,
            f"⏳ Please wait {math.ceil(wait)}s before sending another message.",
        )
        return

    if is_natural_delete_request(sanitized_text):
        await handle_natural_delete_request(update, context)
        return

    try:
        async with state.user_lock(user.id):
            history = await state.store.load_history(user.id, state.settings.history_messages)
            result = await state.ai.chat(
                sanitized_text,
                history,
                user_id=user.id,
                commands=command_summary(),
            )
            await state.store.save_turn(user.id, sanitized_text, result.text)
            state.stats.messages += 1
            state.stats.ai_chats += 1
        sent = await reply_ai(
            update.message,
            result.text,
            reply_markup=_regenerate_keyboard(user.id),
        )
        if sent is not None:
            context.user_data["ai_regenerate"] = {
                str(sent.message_id): {
                    "text": sanitized_text,
                    "history": trim_history(history, state.settings.history_chars),
                }
            }
    except AIUnavailable:
        state.stats.errors += 1
        logger.warning("AI is unavailable for user %s", user.id)
        await reply_ai(update.message, "The AI is unavailable right now. Please try again shortly.")
    except Exception:
        state.stats.errors += 1
        logger.exception("Message handler failed")
        await reply_ai(update.message, "I couldn't process that message. Please try again.")


@callback("regen")
async def handle_regenerate_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    payload: str,
) -> None:
    """Regenerate the AI response attached to this user's message."""
    query = update.callback_query
    user = update.effective_user
    try:
        owner_id = int(payload)
    except ValueError:
        await query.answer("This regenerate button has expired.")
        return
    if user is None or user.id != owner_id:
        await query.answer("This response belongs to another user.", show_alert=True)
        return
    response = query.message
    request = (
        context.user_data.get("ai_regenerate", {}).get(str(response.message_id))
        if response is not None
        else None
    )
    if not isinstance(request, dict):
        await query.answer("This regenerate button has expired.")
        return

    state = get_state(context)
    # The callback dispatcher charges 0.5 tokens; charge the remaining half for an AI call.
    wait = state.limiter.consume(user.id, 0.5)
    if wait > 0:
        await query.answer(f"Please wait {math.ceil(wait)}s before trying again.")
        return
    await query.answer("Generating a fresh response…")
    try:
        async with state.user_lock(user.id):
            result = await state.ai.chat(
                request["text"],
                request["history"],
                user_id=user.id,
                commands=command_summary(),
            )
        try:
            await query.edit_message_text(
                markdown_to_html(result.text),
                parse_mode=ParseMode.HTML,
                reply_markup=_regenerate_keyboard(user.id),
            )
        except BadRequest:
            await query.edit_message_text(
                result.text[:4000],
                parse_mode=None,
                reply_markup=_regenerate_keyboard(user.id),
            )
        state.stats.ai_chats += 1
    except AIUnavailable:
        state.stats.errors += 1
        logger.warning("AI regeneration unavailable for user %s", user.id)
        await response.reply_text("The AI is unavailable right now. Please try again shortly.")
    except Exception:
        state.stats.errors += 1
        logger.exception("AI regeneration failed")
        await response.reply_text("I couldn't regenerate that response. Please try again.")
